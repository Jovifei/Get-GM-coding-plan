"""Playwright 浏览器管理模块 (Async API)"""
import logging
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright, Browser, Page, BrowserContext

logger = logging.getLogger(__name__)


class BrowserManager:
    """浏览器管理器"""

    def __init__(self, config: dict):
        self.config = config
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    async def _launch(self):
        """启动浏览器"""
        self.playwright = await async_playwright().start()

        headless = self.config.get('browser', {}).get('headless', False)

        self.browser = await self.playwright.chromium.launch(
            headless=headless,
            args=['--disable-blink-features=AutomationControlled']
        )

        self.context = await self.browser.new_context(
            viewport={'width': 1280, 'height': 720},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )

        self.page = await self.context.new_page()
        logger.info(f"浏览器启动成功 (headless={headless})")

    def get_page(self) -> Page:
        """获取页面对象"""
        if self.page is None:
            raise RuntimeError("浏览器未初始化")
        return self.page

    async def take_screenshot(self, name: str) -> Optional[str]:
        """截图保存"""
        if not self.config.get('browser', {}).get('screenshot', True):
            return None

        screenshot_dir = Path(__file__).parent.parent / "screenshots"
        screenshot_dir.mkdir(exist_ok=True)

        filepath = screenshot_dir / f"{name}_{self._timestamp()}.png"

        try:
            await self.page.screenshot(path=str(filepath))
            logger.info(f"截图已保存: {filepath}")
            return str(filepath)
        except Exception as e:
            logger.warning(f"截图失败: {e}")
            return None

    async def save_html(self, name: str):
        """保存页面HTML"""
        if not self.config.get('debug', {}).get('save_html', True):
            return

        html_dir = Path(__file__).parent.parent / "debug_html"
        html_dir.mkdir(exist_ok=True)

        filepath = html_dir / f"{name}_{self._timestamp()}.html"

        try:
            content = await self.page.content()
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(content)
            logger.info(f"HTML已保存: {filepath}")
        except Exception as e:
            logger.warning(f"HTML保存失败: {e}")

    def _timestamp(self) -> str:
        """生成时间戳字符串"""
        from datetime import datetime
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    async def save_state(self, path: str):
        """保存当前 context 的登录态到文件"""
        if self.context:
            await self.context.storage_state(path=path)
            logger.info(f"登录态已保存: {path}")

    @staticmethod
    async def load_state(path: str, config: dict):
        """不经过 launch，直接用 playwright + storage_state 创建实例"""
        pw = await async_playwright().start()
        browser = await pw.chromium.launch(
            headless=config.get('browser', {}).get('headless', False),
            args=['--disable-blink-features=AutomationControlled']
        )
        ctx = await browser.new_context(
            storage_state=path,
            viewport={'width': 1280, 'height': 720},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        page = await ctx.new_page()
        logger.info(f"已从文件加载登录态创建实例: {path}")
        return pw, browser, ctx, page

    async def close(self):
        """关闭浏览器"""
        try:
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
            logger.info("浏览器已关闭")
        except Exception as e:
            logger.warning(f"关闭浏览器时出错: {e}")
