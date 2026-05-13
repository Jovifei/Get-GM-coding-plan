"""定时调度模块"""
import asyncio
import logging
import math
from datetime import datetime, timedelta
from typing import Callable, Optional

from src.diagnostics import diagnostic_step
from src.payment import PaymentManager

logger = logging.getLogger(__name__)


def format_remaining_for_log(remaining_seconds: float) -> str:
    if remaining_seconds > 3600:
        hours = math.ceil(remaining_seconds / 3600)
        return f"等待 {hours} 小时..."
    if remaining_seconds > 300:
        minutes = math.ceil(remaining_seconds / 60)
        return f"等待 {minutes} 分钟..."
    if remaining_seconds > 60:
        return f"等待 {remaining_seconds:.0f} 秒..."
    return ""


class Scheduler:
    """定时调度器"""

    def __init__(self, config: dict, task_func: Callable):
        self.config = config
        self.task_func = task_func
        self.purchase_config = config.get('purchase', {})
        self.hour = self.purchase_config.get('hour', 10)
        self.minute = self.purchase_config.get('minute', 0)
        self.second = self.purchase_config.get('second', 0)
        self.start_before = self.purchase_config.get('start_before', 60)  # 提前秒数
        self.end_after = self.purchase_config.get('end_after', 900)  # 持续秒数
        self.running = False

    async def start(self):
        """启动预热调度器"""
        self.running = True
        preheat_config = self.config.get('preheat', {})
        if not preheat_config.get('enabled', True):
            logger.info("预热模式未启用，使用原有调度逻辑")
            with diagnostic_step(logger, "旧版调度"):
                await self._start_legacy()
            return

        login_hour, login_min, login_sec = self._get_preheat_time('login_time', '09:55:00')
        launch_hour, launch_min, launch_sec = self._get_preheat_time('launch_time', '09:57:00')
        click_hour, click_min, click_sec = self._get_preheat_time('click_time', '09:58:00')

        login_time = self._get_today_target(login_hour, login_min, login_sec)
        launch_time = self._get_today_target(launch_hour, launch_min, launch_sec)
        click_time = self._get_today_target(click_hour, click_min, click_sec)

        if datetime.now() >= login_time:
            login_time += timedelta(days=1)
            launch_time += timedelta(days=1)
            click_time += timedelta(days=1)

        logger.info(f"预热调度已启动:")
        logger.info(f"  预热登录: {login_time}")
        logger.info(f"  启动实例: {launch_time}")
        logger.info(f"  开始抢购: {click_time}")

        while self.running:
            now = datetime.now()

            # 阶段1: 等待预热时间
            if now < login_time:
                logger.info(f"等待预热登录: {login_time}")
                with diagnostic_step(logger, "等待预热登录时间"):
                    await self._wait_until(login_time)
                if not self.running:
                    break

                from src.preheat import PreheatManager
                preheat = PreheatManager(self.config)
                with diagnostic_step(logger, "预热登录"):
                    login_ok = await preheat.preheat_login()
                if not login_ok:
                    logger.error("预热登录失败，跳过今日抢购，等待明天")
                    await asyncio.sleep(3600)
                    login_time += timedelta(days=1)
                    launch_time += timedelta(days=1)
                    click_time += timedelta(days=1)
                    continue

            # 阶段2: 等待启动时间
            if not self.running:
                break
            logger.info(f"等待启动实例: {launch_time}")
            with diagnostic_step(logger, "等待启动实例时间"):
                await self._wait_until(launch_time)
            if not self.running:
                break

            n_instances = preheat_config.get('instances', 3)
            with diagnostic_step(logger, f"启动{n_instances}个抢购实例"):
                await preheat.launch_instances(n=n_instances)

            # 阶段3: 等待抢购开始
            if not self.running:
                break
            logger.info(f"等待开始抢购: {click_time}")
            with diagnostic_step(logger, "等待开始抢购时间"):
                await self._wait_until(click_time)
            if not self.running:
                break

            # 阶段4: 并发抢购
            logger.info("开始并发抢购...")
            with diagnostic_step(logger, "并发抢购"):
                result = await preheat.start_purchase_concurrent()

            # 阶段5: 支付
            if result.get("success") and result.get("page"):
                logger.info("进入支付流程...")
                with diagnostic_step(logger, "支付处理"):
                    payment_mgr = PaymentManager(result["page"], self.config)
                    payment_result = await payment_mgr.handle_payment(result)
                if payment_result.get("success"):
                    logger.info("支付成功!")
                else:
                    logger.warning(f"支付未完成: {payment_result.get('reason')}")
            else:
                logger.warning(f"抢购未成功: {result.get('reason', 'unknown')}")

            # 清理
            with diagnostic_step(logger, "清理预热资源"):
                await preheat.cleanup()
            logger.info("本次抢购结束，等待明天...")

            # 更新为明天的时间
            await asyncio.sleep(300)
            login_time += timedelta(days=1)
            launch_time += timedelta(days=1)
            click_time += timedelta(days=1)

    def _parse_time(self, time_str: str):
        """解析 'HH:MM:SS' 格式"""
        parts = time_str.split(':')
        second = int(parts[2]) if len(parts) > 2 else 0
        return int(parts[0]), int(parts[1]), second

    def _get_preheat_time(self, key: str, default: str):
        return self._parse_time(self.config.get('preheat', {}).get(key, default))

    def _get_today_target(self, hour: int, minute: int, second: int = 0) -> datetime:
        """构建今天指定时间点"""
        now = datetime.now()
        return now.replace(hour=hour, minute=minute, second=second, microsecond=0)

    async def _start_legacy(self):
        """原有调度逻辑（预热禁用时使用）"""
        while self.running:
            now = datetime.now()
            target = self._get_today_target(self.hour, self.minute, self.second)
            if now >= target:
                target += timedelta(days=1)
            logger.info(f"下次抢购: {target}")
            await self._wait_until(target)
            if not self.running:
                break
            logger.info("开始执行抢购任务...")
            await self._run_purchase(target, target + timedelta(seconds=self.end_after))
            await asyncio.sleep(60)

    async def _wait_until(self, target: datetime):
        """等待到达目标时间"""
        while datetime.now() < target:
            remaining = (target - datetime.now()).total_seconds()
            if remaining > 3600:
                logger.info(format_remaining_for_log(remaining))
                await asyncio.sleep(1800)  # 半小时检查一次
            elif remaining > 300:
                logger.info(format_remaining_for_log(remaining))
                await asyncio.sleep(60)
            elif remaining > 60:
                logger.info(format_remaining_for_log(remaining))
                await asyncio.sleep(30)
            else:
                await asyncio.sleep(1)

            if not self.running:
                break

    async def _run_purchase(self, target: datetime, end_time: datetime):
        """执行抢购直到结束"""
        retry_count = 0
        max_retries = self.purchase_config.get('max_retries', 10)
        refresh_interval = self.purchase_config.get('refresh_interval', 0.5)

        while datetime.now() < end_time and self.running:
            try:
                # 调用任务函数，传入目标时间
                result = self.task_func(self.config, debug=True, target_time=target)

                if result:
                    logger.info("抢购任务成功!")
                    return

                retry_count += 1
                if retry_count >= max_retries:
                    logger.warning(f"已达到最大重试次数 {max_retries}")
                    break

                logger.info(f"抢购未成功，{refresh_interval}秒后重试 ({retry_count}/{max_retries})")
                await asyncio.sleep(refresh_interval)

            except Exception as e:
                logger.error(f"抢购任务异常: {e}")
                retry_count += 1
                await asyncio.sleep(refresh_interval)

    def stop(self):
        """停止调度器"""
        logger.info("停止调度器...")
        self.running = False
