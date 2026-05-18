# Async Multi-Instance Parallel Purchase Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert GLM_GET from Playwright Sync API to Async API, enabling true parallel multi-instance purchasing with `asyncio.gather()`.

**Architecture:** Replace all `playwright.sync_api` with `playwright.async_api`, convert every class method to `async def`, use `asyncio.gather()` for parallel instance execution with `asyncio.Event` for cross-instance coordination. Add `no_refresh_window` logic to prevent refreshing during the critical 09:59:40~10:00:20 window.

**Tech Stack:** Python 3.11+, asyncio, playwright.async_api, pyyaml

---

## File Structure

| File | Responsibility | Change Type |
|------|---------------|-------------|
| `src/browser.py` | Browser lifecycle (launch, context, page) | Convert sync→async |
| `src/login.py` | Login flow (phone+password) | Convert sync→async |
| `src/coder.py` | Purchase detection, clicking, no_refresh_window | Convert sync→async + logic changes |
| `src/payment.py` | Payment flow (balance, QR code) | Convert sync→async |
| `src/preheat.py` | Multi-instance management, asyncio.gather | Convert sync→async + architecture change |
| `src/scheduler.py` | Daily scheduling, preheat phases | Convert sync→async |
| `src/diagnostics.py` | Logging utilities | No change |
| `config.yaml` | Configuration | Update refresh_interval, remove use_threads |
| `main.py` | CLI entry point | Adapt to asyncio.run() |
| `requirements.txt` | Dependencies | No change (playwright already includes async_api) |

---

## Task 1: Add helper function unit tests (pure logic, no browser)

**Files:**
- Create: `tests/test_helpers.py`

These tests verify pure-logic functions that don't touch the browser, giving us a safety net before we start refactoring.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for pure-logic helper functions in coder.py"""
import pytest
from datetime import datetime, timedelta


def test_calculate_click_window():
    from src.coder import calculate_click_window
    target = datetime(2026, 5, 12, 10, 0, 0)
    start, end = calculate_click_window(target, click_buffer=120, end_after=1200)
    assert start == datetime(2026, 5, 12, 9, 58, 0)
    assert end == datetime(2026, 5, 12, 10, 20, 0)


def test_is_retry_limited_text():
    from src.coder import is_retry_limited_text
    assert is_retry_limited_text("抢购人数过多，请刷新再试") is True
    assert is_retry_limited_text("暂时售罄") is False
    assert is_retry_limited_text("特惠订购") is False
    assert is_retry_limited_text("") is False
    assert is_retry_limited_text("请刷新页面") is True


def test_is_ready_purchase_text():
    from src.coder import is_ready_purchase_text
    assert is_ready_purchase_text("特惠订购") is True
    assert is_ready_purchase_text("立即订购") is True
    assert is_ready_purchase_text("立即购买") is True
    assert is_ready_purchase_text("特惠订购 - 抢购人数过多") is False
    assert is_ready_purchase_text("抢购人数过多") is False
    assert is_ready_purchase_text("暂时售罄") is False
    assert is_ready_purchase_text("") is False


def test_is_ready_purchase_text_handles_subscription_variant():
    """特惠订阅 should be recognized as purchasable (currently NOT in markers — this test will fail)"""
    from src.coder import is_ready_purchase_text
    assert is_ready_purchase_text("特惠订阅") is True


def test_get_subscription_period_label():
    from src.coder import get_subscription_period_label
    assert get_subscription_period_label("monthly") == "连续包月"
    assert get_subscription_period_label("quarterly") == "连续包季"
    assert get_subscription_period_label("yearly") == "连续包年"
    assert get_subscription_period_label("unknown") == "连续包季"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd E:/project/GLM_GET && python -m pytest tests/test_helpers.py -v`
Expected: `test_is_ready_purchase_text_handles_subscription_variant` FAILS (assert False), others PASS

- [ ] **Step 3: Fix `is_ready_purchase_text` to include "特惠订阅"**

In `src/coder.py:28`, change:

```python
def is_ready_purchase_text(text: str) -> bool:
    ready_markers = ("特惠订购", "立即订购", "立即购买", "特惠订阅")
    blocked_markers = ("抢购人数过多", "刷新再试", "售罄", "售完")
    value = text or ""
    return any(marker in value for marker in ready_markers) and not any(marker in value for marker in blocked_markers)
```

- [ ] **Step 4: Run test to verify all pass**

Run: `cd E:/project/GLM_GET && python -m pytest tests/test_helpers.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_helpers.py src/coder.py
git commit -m "feat: add helper tests, fix 特惠订阅 not recognized as purchasable"
```

---

## Task 2: Convert browser.py to async API

**Files:**
- Modify: `src/browser.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for async BrowserManager"""
import pytest
import asyncio
from src.browser import BrowserManager


def test_browser_manager_imports_async():
    """Verify browser.py now uses async_api"""
    import src.browser as bm
    import inspect
    # Check that _launch is now a coroutine function
    assert inspect.iscoroutinefunction(bm.BrowserManager._launch)


@pytest.mark.asyncio
async def test_browser_manager_launch_and_close():
    config = {
        'browser': {'headless': True, 'screenshot': False}
    }
    mgr = BrowserManager(config)
    await mgr._launch()
    page = mgr.get_page()
    assert page is not None
    await mgr.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd E:/project/GLM_GET && python -m pytest tests/test_browser.py -v`
Expected: FAIL — `_launch` is not a coroutine, import uses sync_api

- [ ] **Step 3: Rewrite browser.py with async API**

```python
"""Playwright 浏览器管理模块"""
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd E:/project/GLM_GET && python -m pytest tests/test_browser.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/browser.py tests/test_browser.py
git commit -m "feat: convert browser.py to playwright async_api"
```

---

## Task 3: Convert login.py to async API

**Files:**
- Modify: `src/login.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for async LoginManager"""
import pytest
import inspect
from src.login import LoginManager


def test_login_methods_are_coroutines():
    assert inspect.iscoroutinefunction(LoginManager.login)
    assert inspect.iscoroutinefunction(LoginManager._login_by_account)
    assert inspect.iscoroutinefunction(LoginManager.is_logged_in)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd E:/project/GLM_GET && python -m pytest tests/test_login_async.py -v`
Expected: FAIL — methods are not coroutines

- [ ] **Step 3: Rewrite login.py with async API**

Replace `playwright.sync_api.Page` with `playwright.async_api.Page`. Change every method to `async def`. Add `await` before every page operation (`page.goto`, `page.wait_for_load_state`, `page.screenshot`, `page.locator().first.is_visible()`, `.click()`, `.fill()`, `.inner_text()`, `.all()`). Replace `time.sleep()` with `await asyncio.sleep()`.

Key changes in `src/login.py`:

```python
import asyncio
from playwright.async_api import Page

class LoginManager:
    def __init__(self, page: Page, config: dict):
        # ... same ...

    async def login(self) -> bool:
        if await self.is_logged_in():
            logger.info("已登录")
            return True
        if await self._login_by_account():
            return True
        logger.error("账号登录失败")
        return False

    async def _login_by_account(self) -> bool:
        # ... all page operations become await ...
        # time.sleep(X) → await asyncio.sleep(X)
        ...

    async def is_logged_in(self) -> bool:
        # ... all page operations become await ...
        ...
```

(Full replacement: every `self.page.xxx(...)` becomes `await self.page.xxx(...)`, every `time.sleep(X)` becomes `await asyncio.sleep(X)`, every `btn.is_visible(...)` becomes `await btn.is_visible(...)`, etc.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd E:/project/GLM_GET && python -m pytest tests/test_login_async.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/login.py tests/test_login_async.py
git commit -m "feat: convert login.py to playwright async_api"
```

---

## Task 4: Convert coder.py to async API + no_refresh_window + sprint mode

**Files:**
- Modify: `src/coder.py`

This is the largest change. We convert to async AND add the new time-window logic.

- [ ] **Step 1: Write the failing tests for new time-window logic**

```python
"""Tests for async CoderManager with no_refresh_window"""
import pytest
import inspect
from datetime import datetime, timedelta
from src.coder import CoderManager, should_skip_refresh, get_effective_refresh_interval


def test_coder_methods_are_coroutines():
    from playwright.async_api import Page
    # Can't instantiate with real page, but we can check the class
    assert inspect.iscoroutinefunction(CoderManager.high_frequency_click)
    assert inspect.iscoroutinefunction(CoderManager._refresh_for_retry_if_needed)
    assert inspect.iscoroutinefunction(CoderManager._select_subscription_period)
    assert inspect.iscoroutinefunction(CoderManager._verify_click_success)


def test_should_skip_refresh_in_no_refresh_window():
    target = datetime(2026, 5, 12, 10, 0, 0)
    no_refresh_window = 20  # seconds

    # 09:59:40 — inside window (20s before target)
    now = datetime(2026, 5, 12, 9, 59, 40)
    assert should_skip_refresh(now, target, no_refresh_window) is True

    # 09:59:39 — outside window
    now = datetime(2026, 5, 12, 9, 59, 39)
    assert should_skip_refresh(now, target, no_refresh_window) is False

    # 10:00:20 — outside window (exactly at boundary)
    now = datetime(2026, 5, 12, 10, 0, 20)
    assert should_skip_refresh(now, target, no_refresh_window) is False

    # 10:00:19 — inside window
    now = datetime(2026, 5, 12, 10, 0, 19)
    assert should_skip_refresh(now, target, no_refresh_window) is True


def test_should_skip_refresh_no_window():
    target = datetime(2026, 5, 12, 10, 0, 0)
    now = datetime(2026, 5, 12, 9, 59, 50)
    assert should_skip_refresh(now, target, no_refresh_window=0) is False


def test_get_effective_refresh_interval_sprint_mode():
    target = datetime(2026, 5, 12, 10, 0, 0)

    # Sprint mode: 10:00:00 ~ 10:00:20 → interval should be very small
    now = datetime(2026, 5, 12, 10, 0, 5)
    interval = get_effective_refresh_interval(now, target, base_interval=0.8, no_refresh_window=20)
    assert interval == 999  # effectively no refresh during sprint

    # Normal mode: outside critical window
    now = datetime(2026, 5, 12, 9, 58, 0)
    interval = get_effective_refresh_interval(now, target, base_interval=0.8, no_refresh_window=20)
    assert interval == 0.8
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd E:/project/GLM_GET && python -m pytest tests/test_coder_async.py -v`
Expected: FAIL — `should_skip_refresh`, `get_effective_refresh_interval` not defined; methods not coroutines

- [ ] **Step 3: Rewrite coder.py**

Key changes to `src/coder.py`:

1. Replace `from playwright.sync_api import Page` → `from playwright.async_api import Page`
2. Add `import asyncio`
3. Add new helper functions `should_skip_refresh()` and `get_effective_refresh_interval()`
4. Convert `high_frequency_click()` to `async def` with all `await` on page operations
5. Add `no_refresh_window` logic: skip `_refresh_for_retry_if_needed` when inside window
6. Add sprint mode: when `target_time <= now <= target_time + 20`, use 20ms click interval only (no refresh)
7. Change refresh_interval from 1.5 default to 0.8
8. All `page.locator()`, `.click()`, `.reload()`, `.is_visible()`, `.count()`, `.inner_text()` → `await`

New helper functions to add before `CoderManager` class:

```python
def should_skip_refresh(now: datetime, target_time: datetime, no_refresh_window: int) -> bool:
    """判断当前是否处于禁止刷新窗口 (target - window/2 ~ target + window/2)"""
    if no_refresh_window <= 0:
        return False
    half = no_refresh_window / 2
    window_start = target_time - timedelta(seconds=half)
    window_end = target_time + timedelta(seconds=half)
    return window_start <= now <= window_end


def get_effective_refresh_interval(now: datetime, target_time: datetime, base_interval: float, no_refresh_window: int) -> float:
    """获取当前时刻的有效刷新间隔。冲刺模式返回 999（不刷新）"""
    if no_refresh_window <= 0:
        return base_interval
    half = no_refresh_window / 2
    window_start = target_time - timedelta(seconds=half)
    window_end = target_time + timedelta(seconds=half)
    if window_start <= now <= window_end:
        return 999.0  # 禁止刷新
    return base_interval
```

Changes to `high_frequency_click()`:

```python
async def high_frequency_click(self, stop_event, timeout: int = 20) -> Dict[str, Any]:
    # ... setup unchanged ...

    while datetime.now() < click_deadline:
        if stop_event.is_set():
            return {"success": False, "reason": "被其他实例抢先", "page": self.page}

        now_dt = datetime.now()
        now_ts = time.time()

        # --- no_refresh_window 判断 ---
        in_no_refresh = should_skip_refresh(now_dt, target_time, self.purchase_config.get('no_refresh_window', 20))

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
                    last_refresh_time, refresh_interval, "未找到特惠订购按钮", step_name,
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
            # ... logging ...
            if (is_retry_limited_text(btn_text) or is_disabled is not None) and not in_no_refresh:
                last_refresh_time = await self._refresh_for_retry_if_needed(
                    last_refresh_time, refresh_interval, f"按钮状态为"{btn_text[:30]}"", step_name,
                )
            await asyncio.sleep(0.05)
            continue

        # --- 按钮可用！高频点击 ---
        if not button_available:
            button_available = True
            click_start_time = time.time()
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
            logger.info("高频点击完成，验证结果...", extra={"step": step_name})
            if await self._verify_click_success():
                result["success"] = True
                result["reason"] = "抢购成功"
                return result
            else:
                button_available = False
                click_start_time = time.time()
```

Convert `_refresh_for_retry_if_needed`:

```python
async def _refresh_for_retry_if_needed(self, last_refresh_time, refresh_interval, reason, step_name):
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
```

Convert `_select_subscription_period`, `_select_plan`, `_confirm_order`, `_verify_click_success` — all become `async def` with `await` on page operations. Replace `time.sleep()` with `await asyncio.sleep()`.

- [ ] **Step 4: Run existing helper tests + new async tests**

Run: `cd E:/project/GLM_GET && python -m pytest tests/test_helpers.py tests/test_coder_async.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/coder.py tests/test_coder_async.py
git commit -m "feat: convert coder.py to async, add no_refresh_window and sprint mode"
```

---

## Task 5: Convert payment.py to async API

**Files:**
- Modify: `src/payment.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for async PaymentManager"""
import pytest
import inspect
from src.payment import PaymentManager


def test_payment_methods_are_coroutines():
    assert inspect.iscoroutinefunction(PaymentManager.handle_payment)
    assert inspect.iscoroutinefunction(PaymentManager._try_balance_pay)
    assert inspect.iscoroutinefunction(PaymentManager._check_payment_success)
    assert inspect.iscoroutinefunction(PaymentManager._check_qrcode_required)
    assert inspect.iscoroutinefunction(PaymentManager._get_qrcode_info)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd E:/project/GLM_GET && python -m pytest tests/test_payment_async.py -v`
Expected: FAIL

- [ ] **Step 3: Rewrite payment.py**

```python
"""支付模块"""
import asyncio
import logging
from typing import Dict, Any, Optional

from playwright.async_api import Page

from src.diagnostics import diagnostic_step

logger = logging.getLogger(__name__)


class PaymentManager:
    """支付管理器"""

    def __init__(self, page: Page, config: dict):
        self.page = page
        self.config = config

    async def handle_payment(self, purchase_result: Dict[str, Any]) -> Dict[str, Any]:
        # ... same structure, all page ops → await, time.sleep → await asyncio.sleep ...
        ...

    async def _try_balance_pay(self) -> bool:
        ...

    async def _check_payment_success(self) -> bool:
        ...

    async def _check_qrcode_required(self) -> bool:
        ...

    async def _get_qrcode_info(self) -> Optional[Dict[str, Any]]:
        ...
```

(Every `self.page.locator(...)` call, `.is_visible()`, `.click()`, `.get_attribute()` gets `await`. Every `time.sleep(X)` becomes `await asyncio.sleep(X)`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `cd E:/project/GLM_GET && python -m pytest tests/test_payment_async.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/payment.py tests/test_payment_async.py
git commit -m "feat: convert payment.py to playwright async_api"
```

---

## Task 6: Convert preheat.py to async with asyncio.gather()

**Files:**
- Modify: `src/preheat.py`

This is the core architectural change — replacing threading with asyncio.gather for true parallel execution.

- [ ] **Step 1: Write the failing test**

```python
"""Tests for async PreheatManager"""
import pytest
import inspect
from src.preheat import PreheatManager


def test_preheat_methods_are_coroutines():
    assert inspect.iscoroutinefunction(PreheatManager.preheat_login)
    assert inspect.iscoroutinefunction(PreheatManager.launch_instances)
    assert inspect.iscoroutinefunction(PreheatManager.start_purchase_concurrent)
    assert inspect.iscoroutinefunction(PreheatManager.cleanup)
    assert inspect.iscoroutinefunction(PreheatManager._instance_click)


def test_preheat_uses_asyncio_event():
    """Verify threading.Event is replaced with asyncio.Event"""
    config = {'preheat': {}}
    mgr = PreheatManager(config)
    import asyncio
    assert isinstance(mgr.stop_event, asyncio.Event)
    assert isinstance(mgr.success_event, asyncio.Event)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd E:/project/GLM_GET && python -m pytest tests/test_preheat_async.py -v`
Expected: FAIL — methods not coroutines, still uses threading.Event

- [ ] **Step 3: Rewrite preheat.py**

Key changes:

```python
"""预热登录与多实例并发管理"""
import asyncio
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any

from playwright.async_api import async_playwright

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
        self.stop_event = asyncio.Event()      # was threading.Event
        self.success_event = asyncio.Event()   # was threading.Event
        self.winner_result: Dict[str, Any] = {}
        self.pw = None
        self.browser = None

    async def preheat_login(self) -> bool:
        """预热登录"""
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

    async def launch_instances(self, n: int = 3):
        """启动 n 个浏览器实例"""
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
                await page.goto("https://bigmodel.cn/glm-coding", timeout=30000)
                await page.wait_for_load_state("networkidle", timeout=30000)
                instance = BrowserInstance(id=i, pw=self.pw, browser=self.browser, ctx=ctx, page=page)
                self.instances.append(instance)
                logger.info(f"实例 {i} 启动成功")
            if i < n - 1:
                interval = self.preheat_config.get('instance_launch_interval', 10)
                await asyncio.sleep(interval)

    async def _instance_click(self, instance: BrowserInstance, target_time: datetime) -> Dict[str, Any]:
        """单个实例的高频抢购循环"""
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
        except Exception as e:
            logger.exception(f"实例 {instance.id} 异常: {e}")
            result["reason"] = str(e)
        return result

    async def start_purchase_concurrent(self) -> Dict[str, Any]:
        """用 asyncio.gather 并行执行所有实例的抢购，谁先成功返回谁的结果"""
        if not self.instances:
            return {"success": False, "reason": "没有可用抢购实例", "page": None}

        target_time = self._get_target_time()

        # 并行启动所有实例的抢购任务
        tasks = [
            self._instance_click(inst, target_time)
            for inst in self.instances
        ]
        logger.info(f"使用 asyncio.gather 并行执行 {len(tasks)} 个实例抢购")
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # 检查是否有成功的结果
        if self.success_event.is_set() and self.winner_result:
            return self.winner_result

        # 没有成功，返回第一个非异常结果
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
        hour = self.config.get('purchase', {}).get('hour', 10)
        minute = self.config.get('purchase', {}).get('minute', 0)
        second = self.config.get('purchase', {}).get('second', 0)
        now = datetime.now()
        target = now.replace(hour=hour, minute=minute, second=second, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return target
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd E:/project/GLM_GET && python -m pytest tests/test_preheat_async.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/preheat.py tests/test_preheat_async.py
git commit -m "feat: convert preheat.py to async, use asyncio.gather for parallel instances"
```

---

## Task 7: Convert scheduler.py to async

**Files:**
- Modify: `src/scheduler.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for async Scheduler"""
import pytest
import inspect
from src.scheduler import Scheduler


def test_scheduler_start_is_coroutine():
    assert inspect.iscoroutinefunction(Scheduler.start)
    assert inspect.iscoroutinefunction(Scheduler._wait_until)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd E:/project/GLM_GET && python -m pytest tests/test_scheduler_async.py -v`
Expected: FAIL

- [ ] **Step 3: Rewrite scheduler.py**

Key changes:
- Add `import asyncio`
- `start()` → `async def start()`
- `_wait_until()` → `async def _wait_until()`
- All `time.sleep()` → `await asyncio.sleep()`
- All `preheat.xxx()` calls → `await preheat.xxx()`
- `PaymentManager` calls → `await payment_mgr.xxx()`

```python
"""定时调度模块"""
import asyncio
import logging
import math
from datetime import datetime, timedelta
from typing import Callable, Optional

from src.diagnostics import diagnostic_step
from src.payment import PaymentManager

logger = logging.getLogger(__name__)


class Scheduler:
    """定时调度器"""

    def __init__(self, config: dict, task_func: Callable):
        self.config = config
        self.task_func = task_func
        # ... same init fields ...

    async def start(self):
        """启动预热调度器"""
        self.running = True
        preheat_config = self.config.get('preheat', {})
        if not preheat_config.get('enabled', True):
            logger.info("预热模式未启用，使用原有调度逻辑")
            # Note: legacy path may not be needed, but keep for compatibility
            return

        # ... time setup same as before ...

        while self.running:
            now = datetime.now()

            # 阶段1: 预热登录
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
                    logger.error("预热登录失败，跳过今日抢购")
                    await asyncio.sleep(3600)
                    login_time += timedelta(days=1)
                    launch_time += timedelta(days=1)
                    click_time += timedelta(days=1)
                    continue

            # 阶段2: 启动实例
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

            # 阶段3: 等待抢购
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

            with diagnostic_step(logger, "清理预热资源"):
                await preheat.cleanup()
            logger.info("本次抢购结束，等待明天...")

            await asyncio.sleep(300)
            login_time += timedelta(days=1)
            launch_time += timedelta(days=1)
            click_time += timedelta(days=1)

    async def _wait_until(self, target: datetime):
        """等待到达目标时间"""
        while datetime.now() < target:
            remaining = (target - datetime.now()).total_seconds()
            if remaining > 3600:
                logger.info(format_remaining_for_log(remaining))
                await asyncio.sleep(1800)
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

    def stop(self):
        """停止调度器"""
        logger.info("停止调度器...")
        self.running = False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd E:/project/GLM_GET && python -m pytest tests/test_scheduler_async.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/scheduler.py tests/test_scheduler_async.py
git commit -m "feat: convert scheduler.py to async with asyncio.sleep"
```

---

## Task 8: Update config.yaml and main.py

**Files:**
- Modify: `config.yaml`
- Modify: `main.py`

- [ ] **Step 1: Update config.yaml**

```yaml
# BigModel.cn 抢购配置

account:
  phone: "17368672935"
  password: "521592659aSD"

purchase:
  hour: 10
  minute: 0
  end_after: 1200
  plan_type: "quarterly"
  fallback_plan: "monthly"
  refresh_interval: 0.8          # 从 1.5 降到 0.8

preheat:
  enabled: true
  login_time: "09:55:00"
  launch_time: "09:57:00"
  click_time: "09:58:00"
  instances: 3
  # use_threads 已移除 — async 是唯一方案
  instance_launch_interval: 10
  click_buffer: 120
  no_refresh_window: 20

browser:
  headless: false
  screenshot: true

debug:
  save_html: true
  console_log: true
```

- [ ] **Step 2: Update main.py to use asyncio.run()**

```python
"""
GLM Coding 套餐抢购脚本
用于自动抢购 BigModel.cn 的 GLM Coding Lite 套餐
"""
import argparse
import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

import yaml

from src.diagnostics import diagnostic_step, init_diagnostics
from src.scheduler import Scheduler

# 日志配置
log_dir = Path(__file__).parent / "logs"
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(log_dir / f"glm_get_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log", encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)


def load_config() -> dict:
    """加载配置文件"""
    config_path = Path(__file__).parent / "config.yaml"
    with open(config_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


async def run_purchase(config: dict, debug: bool = False, test_mode: bool = False, target_time: datetime = None):
    """执行一次抢购（test 模式）"""
    from src.preheat import PreheatManager

    preheat = PreheatManager(config)
    try:
        with diagnostic_step(logger, "测试模式-预热登录"):
            login_ok = await preheat.preheat_login()
        if not login_ok:
            logger.error("预热登录失败")
            return False

        n = config.get('preheat', {}).get('instances', 3)
        with diagnostic_step(logger, f"测试模式-启动{n}个抢购实例"):
            await preheat.launch_instances(n=n)
        await asyncio.sleep(2)

        with diagnostic_step(logger, "测试模式-并发抢购"):
            result = await preheat.start_purchase_concurrent()

        if result.get("success") and result.get("page"):
            with diagnostic_step(logger, "测试模式-支付处理"):
                from src.payment import PaymentManager
                payment_mgr = PaymentManager(result["page"], config)
                payment_result = await payment_mgr.handle_payment(result)
            if payment_result.get("success"):
                logger.info("支付成功!")
            else:
                logger.warning(f"支付未完成: {payment_result.get('reason')}")
        else:
            logger.warning(f"抢购未成功: {result.get('reason', 'unknown')}")

        return result.get("success", False)
    finally:
        with diagnostic_step(logger, "测试模式-清理资源"):
            await preheat.cleanup()


async def run_scheduler(config: dict):
    """运行定时抢购"""
    scheduler = Scheduler(config, run_purchase)
    await scheduler.start()


def main():
    parser = argparse.ArgumentParser(description='GLM Coding 套餐抢购脚本')
    parser.add_argument('--mode', choices=['test', 'subscribe'], default='subscribe')
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args()

    config = load_config()
    diagnostic_path = init_diagnostics(log_dir)
    logger.info(f"诊断日志文档: {diagnostic_path}", extra={"step": "diagnostics"})

    if args.debug:
        config['browser']['headless'] = False
        config['debug']['console_log'] = True

    logger.info(f"启动 GLM 抢购脚本 - 模式: {args.mode}")

    if args.mode == 'test':
        asyncio.run(run_purchase(config, debug=True, test_mode=True))
    else:
        asyncio.run(run_scheduler(config))


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run all tests**

Run: `cd E:/project/GLM_GET && python -m pytest tests/ -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add config.yaml main.py
git commit -m "feat: update config.yaml, convert main.py to asyncio.run entry point"
```

---

## Task 9: Full integration smoke test

**Files:**
- No file changes — this is a verification step

- [ ] **Step 1: Run test mode with headless browser**

Run: `cd E:/project/GLM_GET && python main.py --mode test --debug`
Expected:
- 3 browser instances launch
- All 3 instances begin button detection
- Logs show interleaved output from all 3 instances
- No crashes or import errors

- [ ] **Step 2: Verify no_refresh_window works in logs**

Look for the absence of "刷新页面后继续等待" log lines during the 09:59:40~10:00:20 window (if running near that time).

- [ ] **Step 3: Run unit tests one final time**

Run: `cd E:/project/GLM_GET && python -m pytest tests/ -v`
Expected: All PASS

- [ ] **Step 4: Commit any final fixes if needed**

---

## Summary of Changes

| File | Lines Changed | Key Change |
|------|--------------|------------|
| `src/browser.py` | ~120 → ~120 | sync_api → async_api |
| `src/login.py` | ~410 → ~410 | sync_api → async_api, time.sleep → asyncio.sleep |
| `src/coder.py` | ~430 → ~470 | async_api + no_refresh_window + sprint mode + 特惠订阅 |
| `src/payment.py` | ~190 → ~190 | sync_api → async_api |
| `src/preheat.py` | ~200 → ~190 | threading → asyncio, asyncio.gather for parallel |
| `src/scheduler.py` | ~220 → ~210 | time.sleep → asyncio.sleep, async start() |
| `config.yaml` | 33 → 31 | remove use_threads, refresh_interval 1.5→0.8 |
| `main.py` | 127 → ~100 | asyncio.run() entry point |
| `tests/` | 0 → ~150 | New test files for each module |

**Total estimated tasks:** 9
**Estimated time per task:** 10-20 minutes
**Total estimated time:** 2-3 hours
