"""抢购核心模块"""
import asyncio
import logging
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from playwright.async_api import Page

logger = logging.getLogger(__name__)


def calculate_click_window(target_time: datetime, click_buffer: int, end_after: int):
    click_buffer = max(0, float(click_buffer))
    end_after = max(0, float(end_after))
    return (
        target_time - timedelta(seconds=click_buffer),
        target_time + timedelta(seconds=end_after),
    )


def is_retry_limited_text(text: str) -> bool:
    retry_markers = ("抢购人数过多", "刷新再试", "请刷新", "暂不可用")
    return any(marker in (text or "") for marker in retry_markers)


def is_ready_purchase_text(text: str) -> bool:
    ready_markers = ("特惠订购", "立即订购", "立即购买", "特惠订阅")
    blocked_markers = ("抢购人数过多", "刷新再试", "售罄", "售完")
    value = text or ""
    return any(marker in value for marker in ready_markers) and not any(marker in value for marker in blocked_markers)


def get_subscription_period_label(plan_type: str) -> str:
    labels = {
        "monthly": "连续包月",
        "quarterly": "连续包季",
        "yearly": "连续包年",
    }
    return labels.get(plan_type, labels["quarterly"])


def get_refresh_interval(config: dict) -> float:
    purchase_config = config.get("purchase", {})
    preheat_config = config.get("preheat", {})
    return float(purchase_config.get("refresh_interval", preheat_config.get("refresh_interval", 0.8)))


def should_skip_refresh(now: datetime, target_time: datetime, no_refresh_window: int) -> bool:
    """判断当前是否处于禁止刷新窗口

    no_refresh_window 表示目标时间前后各多少秒，窗口总宽度 = 2 * no_refresh_window。
    例如 no_refresh_window=20 时，窗口为 [target-20s, target+20s]。
    """
    if no_refresh_window <= 0:
        return False
    window_start = target_time - timedelta(seconds=no_refresh_window)
    window_end = target_time + timedelta(seconds=no_refresh_window)
    return window_start <= now < window_end


class CoderManager:
    """抢购管理器"""

    def __init__(self, page: Page, config: dict, test_mode: bool = False, target_time: datetime = None, stop_event=None):
        self.page = page
        self.config = config
        self.purchase_config = config.get('purchase', {})
        self.plan_type = self.purchase_config.get('plan_type', 'monthly')
        self.fallback_plan = self.purchase_config.get('fallback_plan', 'quarterly')
        self.test_mode = test_mode
        self.target_time = target_time  # 外部传入的目标时间
        self.stop_event = stop_event if stop_event else asyncio.Event()

    async def purchase(self) -> Dict[str, Any]:
        """执行抢购流程"""
        result = {
            "success": False,
            "reason": "",
            "needs_payment": False,
            "order_id": None,
        }

        try:
            # 打开目标页面
            logger.info("打开 GLM Coding 页面...")
            await self.page.goto("https://bigmodel.cn/glm-coding")
            await self.page.wait_for_load_state("networkidle", timeout=30000)

            # 等待购买按钮出现且可用，然后高频点击
            # 测试模式：等待5秒超时
            # 订阅模式：等待到 end_after 时间（15分钟窗口）
            clicked = await self.high_frequency_click(
                stop_event=self.stop_event,
                timeout=self.purchase_config.get('end_after', 900) if not self.test_mode else 5
            )

            if not clicked.get("success", False):
                if self.test_mode:
                    logger.warning("测试模式：购买按钮暂不可用，跳过点击")
                    result["reason"] = "测试模式：购买按钮暂不可用"
                    return result
                else:
                    result["reason"] = "购买按钮未出现或超时"
                    return result

            # 等待结算页
            await asyncio.sleep(1)

            # 选择套餐
            if not await self._select_plan():
                # 套餐售罄，尝试降级
                logger.warning(f"{self.plan_type} 售罄，尝试降级 {self.fallback_plan}")
                if not await self._select_plan(self.fallback_plan):
                    result["reason"] = f"{self.plan_type} 和 {self.fallback_plan} 都售罄"
                    return result

            # 确认订单
            if not await self._confirm_order():
                result["reason"] = "订单确认失败"
                return result

            logger.info("订单已确认，等待支付")
            result["success"] = True
            result["needs_payment"] = True

            return result

        except Exception as e:
            logger.error(f"抢购异常: {e}")
            result["reason"] = str(e)
            return result

    async def high_frequency_click(self, stop_event, timeout: int = 20) -> Dict[str, Any]:
        """
        高频轮询点击模式，按钮灰色/人数过多时按配置刷新页面。

        Args:
            stop_event: 共享停止事件，任一实例成功则全部停止
            timeout: 超时秒数（从开始检测算起）

        Returns:
            {"success": bool, "reason": str, "page": Page, "instance_id": int}
        """
        step_name = "高频检测购买按钮"
        result = {"success": False, "reason": "", "page": self.page}

        selector_list = [
            'button:has-text("特惠订购")',
            'a:has-text("特惠订购")',
            '[role="button"]:has-text("特惠订购")',
            'text="特惠订购"',
            'button:has-text("特惠订阅")',
            'a:has-text("特惠订阅")',
            'text="特惠订阅"',
            'button:has-text("立即购买 ¥0")',
            'a:has-text("立即购买 ¥0")',
            'button:has-text("¥0")',
            'a:has-text("¥0")',
            'button:has-text("立即购买")',
            'a:has-text("立即购买")',
            'button:has-text("立即订购")',
            'a:has-text("立即订购")',
            '[class*="buy"]',
        ]

        last_log_time = 0
        last_refresh_time = 0
        last_heartbeat_time = 0
        click_start_time = None
        button_available = False
        click_retry_count = 0
        max_click_retries = 3
        clicked_url_before = ""
        refresh_interval = get_refresh_interval(self.config)
        target_time = self.target_time if self.target_time else self._get_target_time()
        preheat_config = self.config.get('preheat', {})
        no_refresh_window = preheat_config.get('no_refresh_window', self.purchase_config.get('no_refresh_window', 20))

        # click_buffer: 提前多少秒开始检测（配置可调，默认 5 秒）
        click_buffer = self.purchase_config.get(
            'click_buffer',
            self.config.get('preheat', {}).get('click_buffer', 5)
        )
        click_window_start, click_deadline = calculate_click_window(
            target_time=target_time,
            click_buffer=click_buffer,
            end_after=timeout,
        )

        if self.test_mode:
            now = datetime.now()
            click_window_start = now
            click_deadline = now + timedelta(seconds=timeout)
            logger.info("测试模式：立即开始高频检测", extra={"step": step_name})
        else:
            logger.info(
                f"目标抢购时间: {target_time}，提前 {click_buffer} 秒开始检测，"
                f"持续到 {click_deadline}",
                extra={"step": step_name}
            )

        # 等待到达目标时间（提前 buffer 秒开始）
        while datetime.now() < click_window_start:
            if stop_event.is_set():
                return {"success": False, "reason": "被其他实例抢先", "page": self.page}
            await asyncio.sleep(0.1)

        logger.info("开始高频检测购买按钮...", extra={"step": step_name})
        await self._select_subscription_period(self.plan_type)

        while datetime.now() < click_deadline:
            if stop_event.is_set():
                return {"success": False, "reason": "被其他实例抢先", "page": self.page}

            now_ts = time.time()
            if now_ts - last_heartbeat_time >= 30:
                remaining = (click_deadline - datetime.now()).total_seconds()
                logger.info(
                    f"仍在检测 Lite/{get_subscription_period_label(self.plan_type)}，剩余 {max(0, remaining):.0f} 秒",
                    extra={"step": step_name}
                )
                last_heartbeat_time = now_ts

            # 检查是否处于禁止刷新窗口
            in_no_refresh = should_skip_refresh(datetime.now(), target_time, no_refresh_window)

            # --- 找按钮 ---
            btn = None
            for selector in selector_list:
                try:
                    count = await self.page.locator(selector).count()
                    if count > 0:
                        candidate = self.page.locator(selector).first
                        if await candidate.is_visible():
                            btn = candidate
                            break
                except Exception:
                    continue

            if btn is None:
                if not in_no_refresh:
                    last_refresh_time = await self._refresh_for_retry_if_needed(
                        last_refresh_time,
                        refresh_interval,
                        "未找到特惠订购按钮",
                        step_name,
                    )
                await asyncio.sleep(0.05)
                continue

            # --- 检查按钮状态 ---
            try:
                is_disabled = await btn.get_attribute('disabled')
                btn_text = await btn.inner_text()
            except Exception:
                await asyncio.sleep(0.02)
                continue

            if is_disabled is not None or not is_ready_purchase_text(btn_text):
                if time.time() - last_log_time > 5:
                    logger.info(f"按钮暂不可用: {btn_text[:30]}...", extra={"step": step_name})
                    last_log_time = time.time()
                click_start_time = None
                if is_retry_limited_text(btn_text) or is_disabled is not None:
                    force_refresh = is_retry_limited_text(btn_text)
                    if force_refresh or not in_no_refresh:
                        last_refresh_time = await self._refresh_for_retry_if_needed(
                            last_refresh_time,
                            refresh_interval,
                            f"按钮状态为\"{btn_text[:30]}\"",
                            step_name,
                        )
                await asyncio.sleep(0.05)
                continue

            # --- 按钮可用！开始高频点击 ---
            if not button_available:
                button_available = True
                click_start_time = time.time()
                clicked_url_before = self.page.url
                click_retry_count = 0
                logger.info(f"检测到可用按钮: {btn_text[:30]}，开始高频点击...", extra={"step": step_name})

            # 高频点击持续 3 秒
            if click_start_time and time.time() - click_start_time < 3:
                try:
                    await btn.click(timeout=200, no_wait_after=True)
                except Exception as e:
                    logger.debug(f"点击异常: {e}")
                    button_available = False
                    await asyncio.sleep(0.01)
                    continue
                await asyncio.sleep(0.02)
            else:
                # 高频点击完成，验证是否成功
                logger.info("高频点击完成，验证结果...", extra={"step": step_name})
                if await self._verify_click_success(clicked_url_before):
                    result["success"] = True
                    result["reason"] = "抢购成功"
                    return result
                else:
                    # Check for new pages/popups
                    new_pages = [p for p in self.page.context.pages if p != self.page]
                    if new_pages:
                        logger.info(f"Detected {len(new_pages)} new page(s), switching")
                        try:
                            new_page = new_pages[-1]
                            await new_page.bring_to_front()
                            await asyncio.sleep(0.5)
                            if await self._verify_click_success(clicked_url_before, page=new_page):
                                self.page = new_page
                                result["success"] = True
                                result["reason"] = "Click succeeded (new tab)"
                                result["page"] = new_page
                                return result
                        except Exception as e:
                            logger.debug(f"Switch to new page failed: {e}")

                    click_retry_count += 1
                    if click_retry_count >= max_click_retries:
                        logger.warning(f"Click retry {click_retry_count} times failed, force refresh")
                        try:
                            await self.page.reload(wait_until="domcontentloaded", timeout=15000)
                            await self._select_subscription_period(self.plan_type)
                        except Exception as exc:
                            logger.warning(f"Force refresh failed: {exc}")
                        click_retry_count = 0
                        last_refresh_time = time.time()
                    button_available = False

        logger.warning("高频点击超时，未检测到成功", extra={"step": step_name})
        result["reason"] = "超时未成功"
        return result

    def _get_target_time(self) -> datetime:
        """获取目标抢购时间

        注意：在订阅模式下，调度器会等待到正确的时间才调用，
        所以这里不应该再加1天。
        """
        hour = self.purchase_config.get('hour', 10)
        minute = self.purchase_config.get('minute', 0)
        second = self.purchase_config.get('second', 0)

        now = datetime.now()
        target = now.replace(hour=hour, minute=minute, second=second, microsecond=0)

        # 如果目标时间已过（调度器已处理过这种情况），直接返回明天的目标
        # 但如果 config 中指定了强制今天，则使用今天
        if target <= now:
            from datetime import timedelta
            target += timedelta(days=1)

        return target

    async def _refresh_for_retry_if_needed(self, last_refresh_time: float, refresh_interval: float, reason: str, step_name: str) -> float:
        now = time.time()
        if now - last_refresh_time < refresh_interval:
            return last_refresh_time

        logger.info(f"{reason}，刷新页面后继续等待", extra={"step": step_name})
        try:
            await self.page.reload(wait_until="domcontentloaded", timeout=15000)
            await self._select_subscription_period(self.plan_type)
        except Exception as exc:
            logger.warning(f"刷新页面失败，继续轮询: {exc}", extra={"step": step_name})
        return now

    async def _select_subscription_period(self, plan_type: str = None) -> bool:
        plan_type = plan_type or self.plan_type
        label = get_subscription_period_label(plan_type)
        selectors = [
            f'text="{label}"',
            f'button:has-text("{label}")',
            f'[role="tab"]:has-text("{label}")',
            f'div:has-text("{label}")',
        ]

        for selector in selectors:
            try:
                element = self.page.locator(selector).first
                if await element.is_visible(timeout=500):
                    await element.click(timeout=500, no_wait_after=True)
                    logger.info(f"已切换到 {label}", extra={"step": "选择订阅周期"})
                    await asyncio.sleep(0.1)
                    return True
            except Exception:
                continue

        logger.warning(f"未找到订阅周期 {label}，继续在当前页面检测", extra={"step": "选择订阅周期"})
        return False

    async def _select_plan(self, plan_type: str = None) -> bool:
        """选择套餐类型"""
        if plan_type is None:
            plan_type = self.plan_type

        try:
            # 根据套餐类型选择
            if plan_type == 'monthly':
                selectors = [
                    'text="连续包月"',
                    'text="包月"',
                    '[class*="monthly"]:visible',
                ]
            else:  # quarterly
                selectors = [
                    'text="连续包季"',
                    'text="包季"',
                    '[class*="quarterly"]:visible',
                ]

            for selector in selectors:
                try:
                    element = self.page.locator(selector).first
                    if await element.is_visible(timeout=3000):
                        await element.click()
                        logger.info(f"已选择 {plan_type} 套餐")
                        await asyncio.sleep(0.3)
                        return True
                except Exception:
                    continue

            logger.warning(f"未找到 {plan_type} 套餐选项")
            return False

        except Exception as e:
            logger.error(f"选择套餐异常: {e}")
            return False

    async def _confirm_order(self) -> bool:
        """确认订单"""
        try:
            confirm_btn = self.page.locator(
                'button:has-text("确认"), button:has-text("提交"), button:has-text("去支付")'
            ).first

            if await confirm_btn.is_visible(timeout=5000):
                await confirm_btn.click()
                logger.info("订单已提交")
                await asyncio.sleep(1)
                return True

            return False

        except Exception as e:
            logger.error(f"确认订单异常: {e}")
            return False

    async def _verify_click_success(self, clicked_url_before: str = "", **kwargs) -> bool:
        """Verify if click succeeded by checking order/payment page"""
        try:
            page = kwargs.get('page', self.page)
            current_url = page.url.lower()
            logger.info(f"Post-click URL: {current_url}")

            # 1. Fast check: URL changed (most reliable signal)
            if clicked_url_before and clicked_url_before.lower() != current_url:
                url_signs = ["/order", "/pay", "/checkout", "/confirm", "/subscribe"]
                if any(sign in current_url for sign in url_signs):
                    logger.info(f"URL navigated to order/payment: {current_url}")
                    return True
                if "/glm-coding" not in current_url:
                    logger.info(f"URL left GLM Coding page: {current_url}")
                    return True

            # 2. Check page elements with 2s timeout
            indicators = [
                'text=确认订单',
                'text=提交订单',
                'text=去支付',
                'text=支付方式',
                'text=应付金额',
                'text=订单详情',
                'text=checkout',
                'button:has-text("确认")',
                'button:has-text("提交")',
                'button:has-text("去支付")',
            ]
            for ind in indicators:
                try:
                    if await page.locator(ind).first.is_visible(timeout=2000):
                        logger.info(f"Order confirmation detected: {ind}")
                        return True
                except Exception:
                    continue

            # 3. Wait for page load then retry with longer timeout
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=3000)
            except Exception:
                pass

            for ind in indicators:
                try:
                    if await page.locator(ind).first.is_visible(timeout=3000):
                        logger.info(f"Order confirmation detected (long timeout): {ind}")
                        return True
                except Exception:
                    continue

            # 4. Still on GLM Coding page = definitely failed
            if "/glm-coding" in current_url:
                logger.debug("Still on GLM Coding page, not in checkout")
                return False

            return False
        except Exception as e:
            logger.debug(f"Click verification error: {e}")
            return False
