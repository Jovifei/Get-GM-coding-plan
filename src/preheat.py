"""预热登录与多实例并发管理 (Async)"""
import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from playwright.async_api import async_playwright

from src.browser import BrowserManager
from src.diagnostics import diagnostic_step
from src.login import LoginManager
from src.coder import CoderManager

logger = logging.getLogger(__name__)

STATE_FILE = Path(__file__).parent.parent / "storage_state.json"


class BrowserInstance:
    """单个浏览器实例"""

    def __init__(self, id: int, pw, browser, ctx, page):
        self.id = id
        self.pw = pw
        self.browser = browser
        self.ctx = ctx
        self.page = page

    async def close(self):
        try:
            await self.ctx.close()
        except Exception:
            pass


class PreheatManager:
    """预热登录 + 多实例并发管理"""

    def __init__(self, config: dict):
        self.config = config
        self.preheat_config = config.get('preheat', {})
        self.instances: list[BrowserInstance] = []
        self.stop_event = asyncio.Event()
        self.success_event = asyncio.Event()
        self.winner_result: Dict[str, Any] = {}
        self.pw = None
        self.browser = None

    # --- 预热登录 ---
    async def preheat_login(self) -> bool:
        """在 9:55 执行：开浏览器 → 登录 → 保存 storage_state → 关闭浏览器"""
        logger.info("开始预热登录...")
        try:
            with diagnostic_step(logger, "预热登录-启动浏览器"):
                mgr = BrowserManager(self.config)
                await mgr._launch()
                page = mgr.get_page()
            with diagnostic_step(logger, "预热登录-账号登录"):
                login_mgr = LoginManager(page, self.config)
                login_ok = await login_mgr.login()
            if not login_ok:
                logger.error("预热登录失败")
                await mgr.close()
                return False
            logger.info("预热登录成功，保存登录态...")
            with diagnostic_step(logger, "预热登录-保存登录态"):
                await mgr.save_state(str(STATE_FILE))
            with diagnostic_step(logger, "预热登录-关闭浏览器"):
                await mgr.close()
            return True
        except Exception as e:
            logger.error(f"预热登录异常: {e}")
            return False

    # --- 启动多实例 ---
    async def launch_instances(self, n: int = 3):
        """在 9:59:00 执行：启动 n 个浏览器实例，均加载 storage_state"""
        logger.info(f"启动 {n} 个抢购实例...")
        with diagnostic_step(logger, "启动Playwright浏览器"):
            self.pw = await async_playwright().start()
            self.browser = await self.pw.chromium.launch(
                headless=self.config.get('browser', {}).get('headless', False),
                args=['--disable-blink-features=AutomationControlled']
            )

        for i in range(n):
            with diagnostic_step(logger, f"启动抢购实例{i}"):
                ctx = await self.browser.new_context(
                    storage_state=str(STATE_FILE),
                    viewport={'width': 1280, 'height': 720},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                )
                page = await ctx.new_page()
                # 提前打开目标页面
                await page.goto("https://bigmodel.cn/glm-coding", timeout=30000)
                await page.wait_for_load_state("networkidle", timeout=30000)
                instance = BrowserInstance(id=i, pw=self.pw, browser=self.browser, ctx=ctx, page=page)
                self.instances.append(instance)
                logger.info(f"实例 {i} 启动成功")
            # 每个实例间隔启动
            if i < n - 1:
                interval = self.preheat_config.get('instance_launch_interval', 10)
                await asyncio.sleep(interval)

    # --- 并发抢购 ---
    async def _instance_click(
        self,
        instance: BrowserInstance,
        target_time: datetime,
        *,
        coder_test_mode: bool = False,
    ) -> Dict[str, Any]:
        """单个实例的高频抢购循环，运行在 asyncio 任务中"""
        result = {"success": False, "reason": "", "page": None, "instance_id": instance.id}
        try:
            with diagnostic_step(logger, f"实例{instance.id}-高频检测"):
                coder = CoderManager(
                    page=instance.page,
                    config=self.config,
                    test_mode=coder_test_mode,
                    target_time=target_time,
                    stop_event=self.stop_event
                )
                # 提前开始检测（从配置读取 buffer 秒数，默认 5）
                purchase_config = self.config.get('purchase', {})
                click_result = await coder.high_frequency_click(
                    stop_event=self.stop_event,
                    timeout=purchase_config.get('end_after', 900)
                )
            if click_result.get("success") and not self.success_event.is_set():
                self.success_event.set()
                self.stop_event.set()
                self.winner_result = click_result
                self.winner_result["instance_id"] = instance.id
                logger.info(f"实例 {instance.id} 抢购成功!")
                return self.winner_result
            result["reason"] = click_result.get("reason", "未抢购成功")
            if click_result.get("detail"):
                result["detail"] = click_result["detail"]
        except Exception as e:
            logger.exception(f"实例 {instance.id} 异常: {e}")
            result["reason"] = str(e)
        return result

    async def start_purchase_concurrent(
        self,
        sale_at: Optional[datetime] = None,
        *,
        coder_test_mode: bool = False,
    ) -> Dict[str, Any]:
        """用 asyncio.gather 并行执行所有实例的抢购。

        sale_at: 由调度器传入的本场开售 datetime（与预热 click 同一天）。
                 为 None 时沿用 _get_target_time()（如测试/临时调用）。
        coder_test_mode: True 时 CoderManager 走测试短窗口（如 main --mode test）。
        """
        if not self.instances:
            return {"success": False, "reason": "没有可用抢购实例", "page": None}

        target_time = sale_at if sale_at is not None else self._get_target_time()
        logger.info(f"并发抢购目标时间 target_time={target_time}")

        tasks = [
            self._instance_click(inst, target_time, coder_test_mode=coder_test_mode)
            for inst in self.instances
        ]
        logger.info(f"使用 asyncio.gather 并行执行 {len(tasks)} 个实例抢购")
        results = await asyncio.gather(*tasks, return_exceptions=True)

        if self.success_event.is_set() and self.winner_result:
            return self.winner_result

        for r in results:
            if isinstance(r, dict):
                return r

        return {"success": False, "reason": "所有实例均未成功", "page": None}

    async def cleanup(self):
        """关闭所有实例"""
        for inst in self.instances:
            with diagnostic_step(logger, f"关闭实例{inst.id}"):
                try:
                    await inst.close()
                except Exception as exc:
                    logger.warning(f"关闭实例 {inst.id} 异常: {exc}", extra={"step": f"关闭实例{inst.id}"})
        if self.browser:
            with diagnostic_step(logger, "关闭浏览器"):
                try:
                    await self.browser.close()
                except Exception as exc:
                    logger.warning(f"关闭浏览器异常: {exc}", extra={"step": "关闭浏览器"})
        if self.pw:
            with diagnostic_step(logger, "停止Playwright"):
                try:
                    await self.pw.stop()
                except Exception as exc:
                    logger.warning(f"停止 Playwright 异常: {exc}", extra={"step": "停止Playwright"})
        logger.info("PreheatManager 资源已清理")

    def _get_target_time(self) -> datetime:
        """无 sale_at 时的后备：按当前日期推算下一场开售（可能为次日）。"""
        from datetime import timedelta

        hour = self.config.get("purchase", {}).get("hour", 10)
        minute = self.config.get("purchase", {}).get("minute", 0)
        second = self.config.get("purchase", {}).get("second", 0)
        now = datetime.now()
        target = now.replace(hour=hour, minute=minute, second=second, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target
