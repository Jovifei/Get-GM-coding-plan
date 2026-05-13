"""登录模块"""
import asyncio
import logging
from typing import Optional

from playwright.async_api import Page

logger = logging.getLogger(__name__)


class LoginManager:
    """登录管理器"""

    LOGIN_URL = "https://bigmodel.cn/login"

    def __init__(self, page: Page, config: dict):
        self.page = page
        self.config = config
        self.phone = config['account']['phone']
        self.password = config['account']['password']

    async def login(self) -> bool:
        """执行登录 - BigModel.cn 支持手机号+密码登录"""
        logger.info("开始登录...")

        # 先检查是否已登录
        if await self.is_logged_in():
            logger.info("已登录")
            return True

        # 优先使用账号登录（手机号+密码）
        if await self._login_by_account():
            return True

        logger.error("账号登录失败")
        return False

    async def _login_by_account(self) -> bool:
        """账号登录 - 使用手机号+密码"""
        try:
            logger.info(f"访问登录页: {self.LOGIN_URL}")
            await self.page.goto(self.LOGIN_URL, timeout=60000)
            await self.page.wait_for_load_state("domcontentloaded", timeout=60000)
            await asyncio.sleep(3)

            # 保存登录页截图用于调试
            await self.page.screenshot(path="debug_login_page.png")
            logger.info("已保存登录页截图 debug_login_page.png")

            # 点击"账号登陆"Tab
            tab_clicked = False
            tab_selectors = [
                'text="账号登陆"',
                'text="账号登录"',
                '.tab:has-text("账号")',
                'button:has-text("账号登陆")',
                'button:has-text("账号登录")'
            ]

            for selector in tab_selectors:
                try:
                    tab = self.page.locator(selector).first
                    if await tab.is_visible(timeout=1000):
                        await tab.click()
                        tab_clicked = True
                        logger.info(f"点击账号登陆Tab: {selector}")
                        await asyncio.sleep(1)
                        break
                except Exception:
                    continue

            if not tab_clicked:
                logger.warning("未找到账号登陆Tab，尝试直接在当前页面登录")

            # 截图查看当前状态
            await self.page.screenshot(path="debug_after_tab.png")
            logger.info("已保存切换Tab后截图 debug_after_tab.png")

            # 输入手机号/用户名
            phone_filled = False
            phone_selectors = [
                'input[placeholder*="用户名/邮箱/手机号"]',
                'input[placeholder*="手机"]',
                'input[placeholder*="账号"]',
                'input[placeholder*="phone"]',
                'input[type="tel"]',
                'input[type="text"]'
            ]

            for selector in phone_selectors:
                try:
                    inp = self.page.locator(selector).first
                    if await inp.is_visible(timeout=1000):
                        await inp.fill(self.phone)
                        phone_filled = True
                        logger.info(f"输入手机号成功: {selector}")
                        break
                except Exception:
                    continue

            if not phone_filled:
                logger.error("无法找到手机号输入框")
                await self._print_page_info()
                return False

            await asyncio.sleep(0.5)

            # 输入密码
            password_filled = False
            password_selectors = [
                'input[type="password"]',
                'input[placeholder*="密码"]',
                'input[placeholder*="password"]'
            ]

            for selector in password_selectors:
                try:
                    inp = self.page.locator(selector).first
                    if await inp.is_visible(timeout=1000):
                        await inp.fill(self.password)
                        password_filled = True
                        logger.info(f"输入密码成功: {selector}")
                        break
                except Exception:
                    continue

            if not password_filled:
                logger.error("无法找到密码输入框")
                await self._print_page_info()
                return False

            await asyncio.sleep(1)

            # 截图查看当前状态
            await self.page.screenshot(path="debug_before_login.png")

            # 点击登录按钮 - 使用多种方法
            login_clicked = False

            # 方法1: 使用 get_by_role
            try:
                btn = self.page.get_by_role("button", name="登录").first
                if await btn.is_visible(timeout=2000):
                    await btn.click()
                    login_clicked = True
                    logger.info("点击登录按钮: get_by_role")
            except Exception:
                pass

            # 方法2: 使用 locator with exact text
            if not login_clicked:
                try:
                    btn = self.page.locator('button:text-is("登录")').first
                    if await btn.is_visible(timeout=1000):
                        await btn.click()
                        login_clicked = True
                        logger.info("点击登录按钮: button:text-is")
                except Exception:
                    pass

            # 方法3: 使用 locator with contains
            if not login_clicked:
                try:
                    btn = self.page.locator('button:has-text("^登录$")').first
                    if await btn.is_visible(timeout=1000):
                        await btn.click()
                        login_clicked = True
                        logger.info("点击登录按钮: button:has-text (regex)")
                except Exception:
                    pass

            # 方法4: 直接通过 text 内容查找
            if not login_clicked:
                try:
                    buttons = await self.page.locator('button:visible').all()
                    for btn in buttons:
                        text = (await btn.inner_text()).strip()
                        if text == "登录":
                            await btn.click()
                            login_clicked = True
                            logger.info(f"点击登录按钮: 遍历找到 text={text}")
                            break
                except Exception:
                    pass

            if not login_clicked:
                logger.error("无法找到登录按钮")
                await self._print_page_info()
                return False

            # 等待登录结果
            logger.info("等待登录结果...")
            await asyncio.sleep(3)

            # 保存登录后截图
            await self.page.screenshot(path="debug_after_login.png")
            logger.info("已保存登录后截图 debug_after_login.png")

            if await self.is_logged_in():
                logger.info("账号登录成功")
                return True

            logger.warning("账号登录未成功")
            return False

        except Exception as e:
            logger.error(f"账号登录异常: {e}")
            return False

    async def _login_by_code(self) -> bool:
        """验证码登录 - BigModel.cn 使用手机号+验证码登录"""
        try:
            logger.info(f"访问登录页: {self.LOGIN_URL}")
            await self.page.goto(self.LOGIN_URL)
            await self.page.wait_for_load_state("networkidle", timeout=30000)
            await asyncio.sleep(2)

            # 页面结构：
            # 输入框: placeholder=请输入手机号
            # 输入框: placeholder=请输入验证码
            # 按钮: text=获取验证码
            # 按钮: text=登录 / 注册

            # 输入手机号
            phone_filled = False
            phone_selectors = [
                'input[placeholder="请输入手机号"]',
                'input[placeholder*="手机"]',
                'input[type="tel"]'
            ]

            for selector in phone_selectors:
                try:
                    inp = self.page.locator(selector).first
                    if await inp.is_visible(timeout=1000):
                        await inp.fill(self.phone)
                        phone_filled = True
                        logger.info(f"输入手机号成功: {selector}")
                        break
                except Exception:
                    continue

            if not phone_filled:
                logger.error("无法找到手机号输入框")
                await self._print_page_info()
                return False

            await asyncio.sleep(0.5)

            # 点击获取验证码
            send_clicked = False
            send_selectors = [
                'button:has-text("获取验证码")',
                'button:has-text("发送验证码")',
                'button:has-text("发送")'
            ]

            for selector in send_selectors:
                try:
                    btn = self.page.locator(selector).first
                    if await btn.is_visible(timeout=1000):
                        await btn.click()
                        send_clicked = True
                        logger.info(f"点击获取验证码: {selector}")
                        break
                except Exception:
                    continue

            if not send_clicked:
                logger.error("无法找到获取验证码按钮")
                return False

            # 等待用户输入验证码
            logger.info("请在终端输入收到的验证码...")
            code = input("请输入验证码: ").strip()

            if not code:
                logger.error("未输入验证码")
                return False

            # 输入验证码
            await asyncio.sleep(1)
            code_filled = False
            code_selectors = [
                'input[placeholder="请输入验证码"]',
                'input[placeholder*="验证码"]'
            ]

            for selector in code_selectors:
                try:
                    inp = self.page.locator(selector).first
                    if await inp.is_visible(timeout=1000):
                        await inp.fill(code)
                        code_filled = True
                        logger.info(f"输入验证码成功")
                        break
                except Exception:
                    continue

            if not code_filled:
                logger.error("无法找到验证码输入框")
                return False

            await asyncio.sleep(0.5)

            # 点击登录/注册按钮
            login_clicked = False
            login_selectors = [
                'button:has-text("登录 / 注册")',
                'button:has-text("登录")',
                'button[type="submit"]'
            ]

            for selector in login_selectors:
                try:
                    btn = self.page.locator(selector).first
                    if await btn.is_visible(timeout=1000):
                        await btn.click()
                        login_clicked = True
                        logger.info(f"点击登录按钮: {selector}")
                        break
                except Exception:
                    continue

            if not login_clicked:
                logger.error("无法找到登录按钮")
                return False

            await asyncio.sleep(3)

            # 保存登录后截图
            await self.page.screenshot(path="debug_after_login.png")
            logger.info("已保存登录后截图 debug_after_login.png")

            if await self.is_logged_in():
                logger.info("验证码登录成功")
                return True

            logger.error("验证码登录失败")
            return False

        except Exception as e:
            logger.error(f"验证码登录异常: {e}")
            return False

    async def is_logged_in(self) -> bool:
        """检查是否已登录"""
        try:
            # 检查是否存在用户头像或退出按钮
            logged_in_indicators = [
                'img[alt="头像"]',
                'img[class*="avatar"]',
                'text="退出"',
                'text="我的"',
                'text="我的订单"',
                '[class*="avatar"]',
                '.user-name',
                '.username'
            ]

            for selector in logged_in_indicators:
                try:
                    if await self.page.locator(selector).first.is_visible(timeout=2000):
                        logger.info(f"检测到已登录: {selector}")
                        return True
                except Exception:
                    continue

            # 检查URL是否包含用户相关页面
            logged_in_urls = ["user", "account", "console", "order", "profile"]
            for url_part in logged_in_urls:
                if url_part in self.page.url.lower():
                    logger.info(f"检测到已登录 (URL包含 {url_part})")
                    return True

            return False

        except Exception:
            return False

    async def _print_page_info(self):
        """打印页面信息用于调试"""
        try:
            logger.info(f"当前URL: {self.page.url}")
            logger.info(f"页面标题: {await self.page.title()}")

            # 列出所有可见的输入框
            inputs = await self.page.locator('input:visible').all()
            logger.info(f"可见输入框数量: {len(inputs)}")
            for i, inp in enumerate(inputs):
                try:
                    placeholder = await inp.get_attribute('placeholder')
                    input_type = await inp.get_attribute('type')
                    logger.info(f"  输入框{i}: type={input_type}, placeholder={placeholder}")
                except Exception:
                    continue

            # 列出所有可见的按钮
            buttons = await self.page.locator('button:visible').all()
            logger.info(f"可见按钮数量: {len(buttons)}")
            for i, btn in enumerate(buttons):
                try:
                    text = await btn.inner_text()
                    btn_type = await btn.get_attribute('type')
                    logger.info(f"  按钮{i}: text={text}, type={btn_type}")
                except Exception:
                    continue
        except Exception as e:
            logger.warning(f"打印页面信息失败: {e}")
