# GLM_GET Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 BigModel.cn GLM Coding Lite 套餐自动抢购脚本

**Architecture:** 使用 Playwright 进行浏览器自动化，模块化设计：配置、浏览器、登录、抢购、支付、定时调度六大模块

**Tech Stack:** Python 3, Playwright, PyYAML, python-dateutil

---

## 文件结构

```
GLM_GET/
├── main.py              # 入口（已存在，需更新）
├── config.yaml          # 配置文件（已存在，需更新）
├── requirements.txt     # 依赖（已存在）
├── src/
│   ├── __init__.py      # 新建
│   ├── config.py        # 新建：配置加载
│   ├── browser.py       # 新建：浏览器管理
│   ├── login.py         # 新建：登录模块
│   ├── coder.py         # 新建：抢购核心
│   ├── payment.py       # 新建：支付处理
│   └── scheduler.py     # 新建：定时调度
└── docs/
    └── specs/
        └── 2026-04-19-glm-get-design.md  # 已存在
```

---

## Task 1: 项目初始化

**Files:**
- Create: `E:/project/GLM_GET/src/__init__.py`
- Modify: `E:/project/GLM_GET/config.yaml`
- Modify: `E:/project/GLM_GET/main.py`

- [ ] **Step 1: Create src/__init__.py**

```python
"""GLM_GET - BigModel.cn GLM Coding 套餐抢购脚本"""
__version__ = "0.1.0"
```

- [ ] **Step 2: Update config.yaml with new structure**

```yaml
# BigModel.cn 抢购配置

account:
  phone: ""      # 手机号
  password: ""   # 密码

purchase:
  hour: 10
  minute: 0
  start_before: 60    # 提前多少秒开始（9:59）
  end_after: 900       # 多少秒后放弃（15分钟=900秒）
  refresh_interval: 0.5 # 刷新间隔（秒）
  plan_type: "monthly"      # 首选套餐
  fallback_plan: "quarterly" # 售罄后降级

browser:
  headless: false
  screenshot: true

debug:
  save_html: true
  console_log: true
```

- [ ] **Step 3: Update main.py to import src modules**

```python
"""
GLM Coding 套餐抢购脚本
用于自动抢购 BigModel.cn 的 GLM Coding Lite 套餐
"""
import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml

from src.browser import BrowserManager
from src.login import LoginManager
from src.coder import CoderManager
from src.payment import PaymentManager
from src.scheduler import Scheduler

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)


def load_config() -> dict:
    """加载配置文件"""
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def run_purchase(config: dict, debug: bool = False):
    """执行一次抢购"""
    browser_mgr = None
    try:
        # 初始化浏览器
        browser_mgr = BrowserManager(config)
        page = browser_mgr.get_page()

        # 登录
        login_mgr = LoginManager(page, config)
        if not login_mgr.login():
            logger.error("登录失败")
            return False
        logger.info("登录成功")

        # 抢购
        coder_mgr = CoderManager(page, config)
        purchase_result = coder_mgr.purchase()

        if purchase_result.get("success"):
            logger.info("抢购成功！")
        else:
            logger.warning(f"抢购未成功: {purchase_result.get('reason', 'unknown')}")

        # 支付
        if purchase_result.get("needs_payment"):
            payment_mgr = PaymentManager(page, config)
            payment_result = payment_mgr.handle_payment(purchase_result)
            if payment_result.get("success"):
                logger.info("支付成功！")
            else:
                logger.warning(f"支付未完成: {payment_result.get('reason', 'unknown')}")

        browser_mgr.take_screenshot("result")
        return purchase_result.get("success", False)

    except Exception as e:
        logger.error(f"执行出错: {e}")
        if debug and browser_mgr:
            browser_mgr.take_screenshot("error")
        return False
    finally:
        if browser_mgr:
            browser_mgr.close()


def run_scheduler(config: dict):
    """运行定时抢购"""
    scheduler = Scheduler(config, run_purchase)
    scheduler.start()


def main():
    parser = argparse.ArgumentParser(description='GLM Coding 套餐抢购脚本')
    parser.add_argument(
        '--mode',
        choices=['test', 'subscribe'],
        default='subscribe',
        help='运行模式: test=立即执行, subscribe=每日定时'
    )
    parser.add_argument(
        '--debug',
        action='store_true',
        help='调试模式'
    )
    args = parser.parse_args()

    config = load_config()

    if args.debug:
        config['browser']['headless'] = False
        config['debug']['console_log'] = True

    logger.info(f"启动 GLM 抢购脚本 - 模式: {args.mode}")

    if args.mode == 'test':
        run_purchase(config, debug=True)
    else:
        run_scheduler(config)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Commit**

```bash
git add src/__init__.py config.yaml main.py
git commit -m "feat: update project structure and config"
```

---

## Task 2: src/config.py

**Files:**
- Create: `E:/project/GLM_GET/src/config.py`

- [ ] **Step 1: Create src/config.py**

```python
"""配置加载模块"""
import logging
from pathlib import Path
from typing import Any, Optional

import yaml

logger = logging.getLogger(__name__)


class Config:
    """配置管理类"""

    _instance: Optional['Config'] = None
    _config: dict = {}

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def load(self, config_path: Optional[str] = None) -> dict:
        """加载配置文件"""
        if config_path is None:
            config_path = Path(__file__).parent.parent / "config.yaml"
        
        with open(config_path, 'r', encoding='utf-8') as f:
            self._config = yaml.safe_load(f)
        
        self._validate()
        logger.info("配置文件加载成功")
        return self._config

    def _validate(self):
        """验证必要配置项"""
        required_sections = ['account', 'purchase', 'browser', 'debug']
        for section in required_sections:
            if section not in self._config:
                raise ValueError(f"配置缺少必要section: {section}")
        
        if not self._config['account'].get('phone'):
            raise ValueError("配置缺少 account.phone")
        
        if not self._config['account'].get('password'):
            logger.warning("account.password 为空，将使用验证码登录")

    def get(self, key: str, default: Any = None) -> Any:
        """获取配置项，支持点号分隔如 'purchase.hour'"""
        keys = key.split('.')
        value = self._config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
            else:
                return default
            if value is None:
                return default
        return value

    @property
    def account(self) -> dict:
        return self._config.get('account', {})

    @property
    def purchase(self) -> dict:
        return self._config.get('purchase', {})

    @property
    def browser(self) -> dict:
        return self._config.get('browser', {})

    @property
    def debug(self) -> dict:
        return self._config.get('debug', {})


# 全局配置实例
config = Config()
```

- [ ] **Step 2: Commit**

```bash
git add src/config.py
git commit -m "feat: add config module"
```

---

## Task 3: src/browser.py

**Files:**
- Create: `E:/project/GLM_GET/src/browser.py`

- [ ] **Step 1: Create src/browser.py**

```python
"""Playwright 浏览器管理模块"""
import logging
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright, Browser, Page, BrowserContext

logger = logging.getLogger(__name__)


class BrowserManager:
    """浏览器管理器"""

    def __init__(self, config: dict):
        self.config = config
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self._launch()

    def _launch(self):
        """启动浏览器"""
        self.playwright = sync_playwright().start()
        
        headless = self.config.get('browser', {}).get('headless', False)
        
        self.browser = self.playwright.chromium.launch(
            headless=headless,
            args=['--disable-blink-features=AutomationControlled']
        )
        
        self.context = self.browser.new_context(
            viewport={'width': 1280, 'height': 720},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        
        self.page = self.context.new_page()
        logger.info(f"浏览器启动成功 (headless={headless})")

    def get_page(self) -> Page:
        """获取页面对象"""
        if self.page is None:
            raise RuntimeError("浏览器未初始化")
        return self.page

    def take_screenshot(self, name: str) -> Optional[str]:
        """截图保存"""
        if not self.config.get('browser', {}).get('screenshot', True):
            return None
        
        screenshot_dir = Path(__file__).parent.parent / "screenshots"
        screenshot_dir.mkdir(exist_ok=True)
        
        filepath = screenshot_dir / f"{name}_{self._timestamp()}.png"
        
        try:
            self.page.screenshot(path=str(filepath))
            logger.info(f"截图已保存: {filepath}")
            return str(filepath)
        except Exception as e:
            logger.warning(f"截图失败: {e}")
            return None

    def save_html(self, name: str):
        """保存页面HTML"""
        if not self.config.get('debug', {}).get('save_html', True):
            return
        
        html_dir = Path(__file__).parent.parent / "debug_html"
        html_dir.mkdir(exist_ok=True)
        
        filepath = html_dir / f"{name}_{self._timestamp()}.html"
        
        try:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(self.page.content())
            logger.info(f"HTML已保存: {filepath}")
        except Exception as e:
            logger.warning(f"HTML保存失败: {e}")

    def _timestamp(self) -> str:
        """生成时间戳字符串"""
        from datetime import datetime
        return datetime.now().strftime("%Y%m%d_%H%M%S")

    def close(self):
        """关闭浏览器"""
        try:
            if self.browser:
                self.browser.close()
            if self.playwright:
                self.playwright.stop()
            logger.info("浏览器已关闭")
        except Exception as e:
            logger.warning(f"关闭浏览器时出错: {e}")
```

- [ ] **Step 2: Commit**

```bash
git add src/browser.py
git commit -m "feat: add browser module with playwright"
```

---

## Task 4: src/login.py

**Files:**
- Create: `E:/project/GLM_GET/src/login.py`

- [ ] **Step 1: Create src/login.py**

```python
"""登录模块"""
import logging
import time
from typing import Optional

from playwright.sync_api import Page

logger = logging.getLogger(__name__)


class LoginManager:
    """登录管理器"""

    def __init__(self, page: Page, config: dict):
        self.page = page
        self.config = config
        self.phone = config['account']['phone']
        self.password = config['account']['password']

    def login(self) -> bool:
        """执行登录，优先密码登录，失败则尝试验证码"""
        logger.info("开始登录...")
        
        # 尝试密码登录
        if self.password:
            if self._login_by_password():
                return True
            logger.warning("密码登录失败，尝试验证码登录")
        
        # 验证码登录
        return self._login_by_code()

    def _login_by_password(self) -> bool:
        """密码登录"""
        try:
            self.page.goto("https://bigmodel.cn/login")
            self.page.wait_for_load_state("networkidle", timeout=30000)
            
            # 输入手机号
            phone_input = self.page.locator('input[type="text"], input[placeholder*="手机"]').first
            phone_input.fill(self.phone)
            
            # 输入密码
            password_input = self.page.locator('input[type="password"]').first
            password_input.fill(self.password)
            
            # 点击登录按钮
            login_btn = self.page.locator('button[type="submit"], button:has-text("登录")').first
            login_btn.click()
            
            # 等待登录结果
            time.sleep(2)
            
            if self.is_logged_in():
                logger.info("密码登录成功")
                return True
            
            logger.warning("密码登录未成功")
            return False
            
        except Exception as e:
            logger.error(f"密码登录异常: {e}")
            return False

    def _login_by_code(self) -> bool:
        """验证码登录"""
        try:
            self.page.goto("https://bigmodel.cn/login")
            self.page.wait_for_load_state("networkidle", timeout=30000)
            
            # 点击切换到验证码登录
            code_login_tab = self.page.locator('text="验证码登录", text="短信登录"').first
            if code_login_tab:
                code_login_tab.click()
                time.sleep(0.5)
            
            # 输入手机号
            phone_input = self.page.locator('input[type="text"], input[placeholder*="手机"]').first
            phone_input.fill(self.phone)
            
            # 点击获取验证码
            send_btn = self.page.locator('button:has-text("获取验证码"), button:has-text("发送")').first
            send_btn.click()
            
            # 等待用户输入验证码（这里需要人工介入，脚本暂停）
            logger.info("请在终端输入收到的验证码...")
            code = input("请输入验证码: ").strip()
            
            if not code:
                logger.error("未输入验证码")
                return False
            
            # 输入验证码
            code_input = self.page.locator('input[type="text"]:nth-match(:visible, 2)')
            code_input.fill(code)
            
            # 点击登录
            login_btn = self.page.locator('button[type="submit"], button:has-text("登录")').first
            login_btn.click()
            
            time.sleep(2)
            
            if self.is_logged_in():
                logger.info("验证码登录成功")
                return True
            
            logger.error("验证码登录失败")
            return False
            
        except Exception as e:
            logger.error(f"验证码登录异常: {e}")
            return False

    def is_logged_in(self) -> bool:
        """检查是否已登录"""
        try:
            # 检查是否存在用户头像或退出按钮
            logged_in_indicators = [
                'img[alt="头像"]',
                'text="退出"',
                'text="我的"',
                '[class*="avatar"]',
            ]
            
            for selector in logged_in_indicators:
                if self.page.locator(selector).first.is_visible(timeout=2000):
                    return True
            
            # 检查URL是否包含个人中心
            if "user" in self.page.url or "account" in self.page.url:
                return True
            
            return False
            
        except Exception:
            return False
```

- [ ] **Step 2: Commit**

```bash
git add src/login.py
git commit -m "feat: add login module with password and code support"
```

---

## Task 5: src/coder.py

**Files:**
- Create: `E:/project/GLM_GET/src/coder.py`

- [ ] **Step 1: Create src/coder.py**

```python
"""抢购核心模块"""
import logging
import time
from datetime import datetime
from typing import Optional, Dict, Any

from playwright.sync_api import Page

logger = logging.getLogger(__name__)


class CoderManager:
    """抢购管理器"""

    def __init__(self, page: Page, config: dict):
        self.page = page
        self.config = config
        self.purchase_config = config.get('purchase', {})
        self.plan_type = self.purchase_config.get('plan_type', 'monthly')
        self.fallback_plan = self.purchase_config.get('fallback_plan', 'quarterly')

    def purchase(self) -> Dict[str, Any]:
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
            self.page.goto("https://bigmodel.cn/glm-coding")
            self.page.wait_for_load_state("networkidle", timeout=30000)
            
            # 等待购买按钮出现
            purchase_btn = self._wait_for_purchase_button()
            if not purchase_btn:
                result["reason"] = "购买按钮未出现"
                return result
            
            # 10:00 准点点击
            target_time = self._get_target_time()
            self._wait_until_target(target_time)
            
            logger.info("准点点击购买按钮!")
            purchase_btn.click()
            
            # 等待结算页
            time.sleep(1)
            
            # 选择套餐
            if not self._select_plan():
                # 套餐售罄，尝试降级
                logger.warning(f"{self.plan_type} 售罄，尝试降级 {self.fallback_plan}")
                if not self._select_plan(self.fallback_plan):
                    result["reason"] = f"{self.plan_type} 和 {self.fallback_plan} 都售罄"
                    return result
            
            # 确认订单
            if not self._confirm_order():
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

    def _wait_for_purchase_button(self) -> Optional[Any]:
        """等待购买按钮出现"""
        selectors = [
            'button:has-text("立即购买")',
            'button:has-text("购买")',
            '[class*="buy"]:visible',
            '[class*="purchase"]:visible',
        ]
        
        for selector in selectors:
            try:
                btn = self.page.locator(selector).first
                if btn.is_visible(timeout=5000):
                    return btn
            except Exception:
                continue
        
        return None

    def _get_target_time(self) -> datetime:
        """获取目标抢购时间"""
        hour = self.purchase_config.get('hour', 10)
        minute = self.purchase_config.get('minute', 0)
        second = self.purchase_config.get('second', 0)
        
        now = datetime.now()
        target = now.replace(hour=hour, minute=minute, second=second, microsecond=0)
        
        # 如果目标时间已过，放在明天
        if target <= now:
            from datetime import timedelta
            target += timedelta(days=1)
        
        return target

    def _wait_until_target(self, target_time: datetime):
        """等待到达目标时间"""
        refresh_interval = self.purchase_config.get('refresh_interval', 0.5)
        
        while datetime.now() < target_time:
            remaining = (target_time - datetime.now()).total_seconds()
            if remaining > 60:
                logger.info(f"等待 {remaining:.0f} 秒...")
                time.sleep(min(remaining - 55, 5))  # 提前55秒开始快速刷新
            else:
                time.sleep(refresh_interval)

    def _select_plan(self, plan_type: str = None) -> bool:
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
                    if element.is_visible(timeout=3000):
                        element.click()
                        logger.info(f"已选择 {plan_type} 套餐")
                        time.sleep(0.3)
                        return True
                except Exception:
                    continue
            
            logger.warning(f"未找到 {plan_type} 套餐选项")
            return False
            
        except Exception as e:
            logger.error(f"选择套餐异常: {e}")
            return False

    def _confirm_order(self) -> bool:
        """确认订单"""
        try:
            confirm_btn = self.page.locator(
                'button:has-text("确认"), button:has-text("提交"), button:has-text("去支付")'
            ).first
            
            if confirm_btn.is_visible(timeout=5000):
                confirm_btn.click()
                logger.info("订单已提交")
                time.sleep(1)
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"确认订单异常: {e}")
            return False
```

- [ ] **Step 2: Commit**

```bash
git add src/coder.py
git commit -m "feat: add coder module for purchase logic"
```

---

## Task 6: src/payment.py

**Files:**
- Create: `E:/project/GLM_GET/src/payment.py`

- [ ] **Step 1: Create src/payment.py**

```python
"""支付模块"""
import logging
import time
from typing import Dict, Any, Optional

from playwright.sync_api import Page

logger = logging.getLogger(__name__)


class PaymentManager:
    """支付管理器"""

    def __init__(self, page: Page, config: dict):
        self.page = page
        self.config = config

    def handle_payment(self, purchase_result: Dict[str, Any]) -> Dict[str, Any]:
        """处理支付流程"""
        result = {
            "success": False,
            "reason": "",
            "payment_url": None,
        }
        
        try:
            # 尝试余额支付
            if self._try_balance_pay():
                result["success"] = True
                result["reason"] = "余额支付成功"
                return result
            
            # 余额不足，获取扫码支付链接
            logger.info("余额不足，获取扫码支付...")
            qr_result = self._get_qrcode_info()
            if qr_result:
                result["payment_url"] = qr_result.get("url")
                result["qrcode_data"] = qr_result.get("qrcode")
                result["reason"] = "扫码支付待处理"
                logger.info(f"扫码支付链接: {result['payment_url']}")
                return result
            
            result["reason"] = "支付方式获取失败"
            return result
            
        except Exception as e:
            logger.error(f"支付处理异常: {e}")
            result["reason"] = str(e)
            return result

    def _try_balance_pay(self) -> bool:
        """尝试余额支付"""
        try:
            # 查找余额支付选项
            balance_selectors = [
                'text="余额支付"',
                'text="账户余额"',
                '[class*="balance"]:visible',
            ]
            
            balance_selected = False
            for selector in balance_selectors:
                try:
                    element = self.page.locator(selector).first
                    if element.is_visible(timeout=2000):
                        element.click()
                        balance_selected = True
                        break
                except Exception:
                    continue
            
            if not balance_selected:
                logger.info("未找到余额支付选项")
                return False
            
            # 点击确认支付
            pay_btn = self.page.locator(
                'button:has-text("确认支付"), button:has-text("立即支付"), button:has-text("支付")'
            ).first
            
            if pay_btn.is_visible(timeout=3000):
                pay_btn.click()
                logger.info("已点击余额支付")
                
                # 等待支付结果
                time.sleep(3)
                
                # 检查是否成功
                if self._check_payment_success():
                    return True
                
                # 检查是否需要扫码
                if self._check_qrcode_required():
                    logger.info("余额不足，需要扫码支付")
                    return False
                
            return False
            
        except Exception as e:
            logger.warning(f"余额支付尝试异常: {e}")
            return False

    def _check_payment_success(self) -> bool:
        """检查支付是否成功"""
        success_indicators = [
            'text="支付成功"',
            'text="购买成功"',
            'text="已完成"',
            'text="success"',
        ]
        
        for selector in success_indicators:
            try:
                if self.page.locator(selector).first.is_visible(timeout=2000):
                    logger.info("检测到支付成功")
                    return True
            except Exception:
                continue
        
        return False

    def _check_qrcode_required(self) -> bool:
        """检查是否需要扫码"""
        qr_indicators = [
            'text="扫码支付"',
            'text="二维码"',
            '[class*="qrcode"]:visible',
            '[class*="qr-code"]:visible',
        ]
        
        for selector in qr_indicators:
            try:
                if self.page.locator(selector).first.is_visible(timeout=2000):
                    return True
            except Exception:
                continue
        
        return False

    def _get_qrcode_info(self) -> Optional[Dict[str, Any]]:
        """获取扫码支付信息"""
        try:
            result = {}
            
            # 获取二维码图片
            qr_selectors = [
                'img[class*="qrcode"]',
                'img[class*="qr-code"]',
                '[class*="qrcode"] img',
            ]
            
            for selector in qr_selectors:
                try:
                    qr_img = self.page.locator(selector).first
                    if qr_img.is_visible(timeout=3000):
                        result["qrcode"] = qr_img.get_attribute("src")
                        break
                except Exception:
                    continue
            
            # 获取支付链接
            link_selectors = [
                'text="支付链接"',
                '[class*="pay-link"]',
                'a[class*="payment"]',
            ]
            
            for selector in link_selectors:
                try:
                    link = self.page.locator(selector).first
                    if link.is_visible(timeout=2000):
                        result["url"] = link.get_attribute("href")
                        break
                except Exception:
                    continue
            
            if result:
                return result
            
            return None
            
        except Exception as e:
            logger.error(f"获取扫码支付信息异常: {e}")
            return None
```

- [ ] **Step 2: Commit**

```bash
git add src/payment.py
git commit -m "feat: add payment module with balance and qrcode support"
```

---

## Task 7: src/scheduler.py

**Files:**
- Create: `E:/project/GLM_GET/src/scheduler.py`

- [ ] **Step 1: Create src/scheduler.py**

```python
"""定时调度模块"""
import logging
import time
import threading
from datetime import datetime, timedelta
from typing import Callable, Optional

logger = logging.getLogger(__name__)


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

    def start(self):
        """启动调度器"""
        self.running = True
        logger.info(f"调度器启动，每日 {self.hour}:{self.minute:02d} 抢购")
        
        while self.running:
            now = datetime.now()
            target = self._get_today_target()
            
            # 如果今天目标时间已过，计算明天的
            if now >= target:
                target = target + timedelta(days=1)
            
            # 计算启动时间（提前 start_before 秒）
            start_time = target - timedelta(seconds=self.start_before)
            
            # 计算结束时间
            end_time = target + timedelta(seconds=self.end_after)
            
            logger.info(f"下次抢购: {target}, 准备开始: {start_time}, 结束时间: {end_time}")
            
            # 等待到达启动时间
            self._wait_until(start_time)
            
            if not self.running:
                break
            
            # 执行抢购任务
            logger.info("开始执行抢购任务...")
            self._run_purchase(target, end_time)
            
            # 等待一下次循环
            time.sleep(60)

    def _get_today_target(self) -> datetime:
        """获取今天的目标时间"""
        now = datetime.now()
        target = now.replace(
            hour=self.hour, 
            minute=self.minute, 
            second=self.second, 
            microsecond=0
        )
        return target

    def _wait_until(self, target: datetime):
        """等待到达目标时间"""
        while datetime.now() < target:
            remaining = (target - datetime.now()).total_seconds()
            if remaining > 3600:
                logger.info(f"等待 {remaining/3600:.1f} 小时...")
                time.sleep(1800)  # 半小时检查一次
            elif remaining > 300:
                logger.info(f"等待 {remaining/60:.1f} 分钟...")
                time.sleep(60)
            elif remaining > 60:
                logger.info(f"等待 {remaining:.0f} 秒...")
                time.sleep(30)
            else:
                time.sleep(1)
            
            if not self.running:
                break

    def _run_purchase(self, target: datetime, end_time: datetime):
        """执行抢购直到结束"""
        retry_count = 0
        max_retries = self.purchase_config.get('max_retries', 10)
        refresh_interval = self.purchase_config.get('refresh_interval', 0.5)
        
        while datetime.now() < end_time and self.running:
            try:
                # 调用任务函数
                result = self.task_func(self.config, debug=True)
                
                if result:
                    logger.info("抢购任务成功!")
                    return
                
                retry_count += 1
                if retry_count >= max_retries:
                    logger.warning(f"已达到最大重试次数 {max_retries}")
                    break
                
                logger.info(f"抢购未成功，{refresh_interval}秒后重试 ({retry_count}/{max_retries})")
                time.sleep(refresh_interval)
                
            except Exception as e:
                logger.error(f"抢购任务异常: {e}")
                retry_count += 1
                time.sleep(refresh_interval)

    def stop(self):
        """停止调度器"""
        logger.info("停止调度器...")
        self.running = False
```

- [ ] **Step 2: Commit**

```bash
git add src/scheduler.py
git commit -m "feat: add scheduler module for timed purchase"
```

---

## Task 8: 集成测试

**Files:**
- Modify: `E:/project/GLM_GET/main.py`（验证导入正确）

- [ ] **Step 1: 验证所有模块导入**

```bash
cd E:/project/GLM_GET
python -c "from src.browser import BrowserManager; from src.login import LoginManager; from src.coder import CoderManager; from src.payment import PaymentManager; from src.scheduler import Scheduler; print('All imports OK')"
```

- [ ] **Step 2: 验证配置文件**

```bash
python -c "from src.config import config; config.load(); print('Config loaded:', config.account.get('phone', 'NO_PHONE'))"
```

- [ ] **Step 3: Commit**

```bash
git add -A
git commit -m "feat: complete GLM_GET core modules"
```

---

## 自检清单

- [x] Spec覆盖：所有需求都有对应Task
- [x] 无占位符：所有步骤都有实际代码
- [x] 类型一致性：方法签名一致
- [x] 提交规范：每个Task有独立commit

---

Plan complete. 两个执行选项：

**1. Subagent-Driven (推荐)** - 我派发子任务，并行执行，快速迭代

**2. Inline Execution** - 在当前会话执行，有检查点

选哪个？