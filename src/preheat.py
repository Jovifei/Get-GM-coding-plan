"""预热登录与多实例并发管理"""
import logging
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, Callable

from playwright.sync_api import sync_playwright

from src.browser import BrowserManager
from src.diagnostics import diagnostic_step
from src.login import LoginManager
from src.coder import CoderManager
from src.payment import PaymentManager

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

    def close(self):
        try:
            self.ctx.close()
        except Exception:
            pass


class PreheatManager:
    """预热登录 + 多实例并发管理"""

    def __init__(self, config: dict):
        self.config = config
        self.preheat_config = config.get('preheat', {})
        self.instances: list[BrowserInstance] = []
        self.stop_event = threading.Event()
        self.success_event = threading.Event()
        self.winner_result: Dict[str, Any] = {}
        self.lock = threading.Lock()
        self.pw = None
        self.browser = None

    # --- 预热登录 ---
    def preheat_login(self) -> bool:
        """在 9:55 执行：开浏览器 → 登录 → 保存 storage_state → 关闭浏览器"""
        logger.info("开始预热登录...")
        try:
            with diagnostic_step(logger, "预热登录-启动浏览器"):
                mgr = BrowserManager(self.config)
                page = mgr.get_page()
            with diagnostic_step(logger, "预热登录-账号登录"):
                login_mgr = LoginManager(page, self.config)
                login_ok = login_mgr.login()
            if not login_ok:
                logger.error("预热登录失败")
                mgr.close()
                return False
            logger.info("预热登录成功，保存登录态...")
            with diagnostic_step(logger, "预热登录-保存登录态"):
                mgr.save_state(str(STATE_FILE))
            with diagnostic_step(logger, "预热登录-关闭浏览器"):
                mgr.close()
            return True
        except Exception as e:
            logger.error(f"预热登录异常: {e}")
            return False

    # --- 启动多实例 ---
    def launch_instances(self, n: int = 3):
        """在 9:59:00 执行：启动 n 个浏览器实例，均加载 storage_state"""
        logger.info(f"启动 {n} 个抢购实例...")
        with diagnostic_step(logger, "启动Playwright浏览器"):
            self.pw = sync_playwright().start()
            self.browser = self.pw.chromium.launch(
                headless=self.config.get('browser', {}).get('headless', False),
                args=['--disable-blink-features=AutomationControlled']
            )

        for i in range(n):
            with diagnostic_step(logger, f"启动抢购实例{i}"):
                ctx = self.browser.new_context(
                    storage_state=str(STATE_FILE),
                    viewport={'width': 1280, 'height': 720},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                )
                page = ctx.new_page()
                # 提前打开目标页面
                page.goto("https://bigmodel.cn/glm-coding", timeout=30000)
                page.wait_for_load_state("networkidle", timeout=30000)
                instance = BrowserInstance(id=i, pw=self.pw, browser=self.browser, ctx=ctx, page=page)
                self.instances.append(instance)
                logger.info(f"实例 {i} 启动成功")
            # 每个实例间隔启动
            if i < n - 1:
                interval = self.preheat_config.get('instance_launch_interval', 10)
                time.sleep(interval)

    # --- 并发抢购 ---
    def _instance_click(self, instance: BrowserInstance, target_time: datetime) -> Dict[str, Any]:
        """单个实例的高频抢购循环，运行在独立线程中"""
        result = {"success": False, "reason": "", "page": None, "instance_id": instance.id}
        try:
            with diagnostic_step(logger, f"实例{instance.id}-高频检测"):
                coder = CoderManager(
                    page=instance.page,
                    config=self.config,
                    test_mode=False,
                    target_time=target_time,
                    stop_event=self.stop_event
                )
                # 提前开始检测（从配置读取 buffer 秒数，默认 5）
                purchase_config = self.config.get('purchase', {})
                click_result = coder.high_frequency_click(
                    stop_event=self.stop_event,
                    timeout=purchase_config.get('end_after', 900)
                )
            if click_result.get("success") and not self.success_event.is_set():
                with self.lock:
                    if not self.success_event.is_set():
                        self.success_event.set()
                        self.stop_event.set()
                        self.winner_result = click_result
                        self.winner_result["instance_id"] = instance.id
                        logger.info(f"实例 {instance.id} 抢购成功!")
                        return self.winner_result
            result["reason"] = click_result.get("reason", "未抢购成功")
        except Exception as e:
            logger.exception(f"实例 {instance.id} 异常: {e}")
            result["reason"] = str(e)
        return result

    def start_purchase_concurrent(self) -> Dict[str, Any]:
        """启动 n 个线程并发执行抢购，谁先成功返回谁的结果"""
        threads = []
        target_time = self._get_target_time()
        if not self.preheat_config.get('use_threads', False):
            if not self.instances:
                return {"success": False, "reason": "没有可用抢购实例", "page": None}
            logger.info("使用主线程持续抢购，避免 Playwright Sync API 跨线程提前中断")
            return self._instance_click(self.instances[0], target_time)

        for inst in self.instances:
            with diagnostic_step(logger, f"启动抢购线程{inst.id}"):
                t = threading.Thread(target=self._instance_click, args=(inst, target_time))
                t.start()
                threads.append(t)
            time.sleep(0.2)  # 稍微错开启动顺序

        # 等待任一成功或全部结束
        for index, t in enumerate(threads):
            with diagnostic_step(logger, f"等待抢购线程{index}结束"):
                t.join()

        # 如果没有任何成功，返回失败
        if not self.success_event.is_set():
            return {"success": False, "reason": "所有实例均未成功", "page": None}
        return self.winner_result if self.winner_result else {"success": False, "reason": "未获取到成功结果", "page": None}

    def cleanup(self):
        """关闭所有实例"""
        for inst in self.instances:
            with diagnostic_step(logger, f"关闭实例{inst.id}"):
                try:
                    inst.close()
                except Exception as exc:
                    logger.warning(f"关闭实例 {inst.id} 异常: {exc}", extra={"step": f"关闭实例{inst.id}"})
        if self.browser:
            with diagnostic_step(logger, "关闭浏览器"):
                try:
                    self.browser.close()
                except Exception as exc:
                    logger.warning(f"关闭浏览器异常: {exc}", extra={"step": "关闭浏览器"})
        if self.pw:
            with diagnostic_step(logger, "停止Playwright"):
                try:
                    self.pw.stop()
                except Exception as exc:
                    logger.warning(f"停止 Playwright 异常: {exc}", extra={"step": "停止Playwright"})
        logger.info("PreheatManager 资源已清理")

    def _get_target_time(self) -> datetime:
        hour = self.config.get('purchase', {}).get('hour', 10)
        minute = self.config.get('purchase', {}).get('minute', 0)
        second = self.config.get('purchase', {}).get('second', 0)
        now = datetime.now()
        target = now.replace(hour=hour, minute=minute, second=second, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target
