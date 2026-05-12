# GLM_GET 预热并发抢购实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 GLM_GET 从"冷启动单实例"模式改造为"预热登录 + 多实例并发"模式，消除15秒登录延迟，实现3个浏览器实例在 10:00:00 同步高频点击。

**Architecture:** 通过 `PreheatManager` 管理预热登录（9:55）和3个并发实例（9:59），三个实例共享 Playwright `storage_state` 免登录，通过 `threading.Event` 协调谁先成功。`CoderManager` 改造为非刷新高频轮询，提前5秒开始检测。

**Tech Stack:** Python, Playwright (sync_api), threading, yaml

---

## 文件变更总览

```
src/browser.py      # 改造：新增 save_state() / load_state()
src/preheat.py      # 新增：PreheatManager（核心）
src/coder.py        # 改造：high_frequency_click(stop_event) + 非刷新模式
src/scheduler.py    # 改造：预热 + 并发调度
src/purchase.py     # 删除：废弃组件
src/payment.py      # 不变
src/login.py        # 不变
src/config.py       # 不变
main.py             # 改造：调用 PreheatManager
config.yaml         # 扩展：新增 preheat 配置段
```

---

## Task 1: BrowserManager 新增 storage_state 管理

**Files:**
- Modify: `src/browser.py`

**验证参考:**
- `src/login.py:40-44` — 现有登录流程，确认 BrowserManager 的 context 在 login 之后处于已登录状态
- `src/scheduler.py:16-21` — 配置读取模式参考

- [ ] **Step 1: 读取现有 browser.py 确认结构**

确认 `BrowserManager.__init__` 中 `self.context` 的赋值位置，确认 `launch()` 方法的完整签名。

- [ ] **Step 2: 在 BrowserManager 新增 save_state 方法**

```python
def save_state(self, path: str):
    """保存当前 context 的登录态到文件"""
    if self.context:
        self.context.storage_state(path=path)
        logger.info(f"登录态已保存: {path}")
```

- [ ] **Step 3: 在 BrowserManager 新增 load_state 方法**

```python
def load_state(self, path: str):
    """从文件加载登录态创建新 context（替代默认 context）"""
    ctx = self.browser.new_context(
        storage_state=path,
        viewport={'width': 1280, 'height': 720},
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    )
    logger.info(f"已从文件加载登录态: {path}")
    return ctx
```

- [ ] **Step 4: 新增 load_state_without_launch 方法（独立使用）**

```python
@staticmethod
def load_state(path: str, config: dict):
    """不经过 launch，直接用已有 browser 加载 storage_state"""
    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        headless=config.get('browser', {}).get('headless', False),
        args=['--disable-blink-features=AutomationControlled']
    )
    ctx = browser.new_context(
        storage_state=path,
        viewport={'width': 1280, 'height': 720},
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    )
    page = ctx.new_page()
    logger.info(f"已从文件加载登录态创建实例: {path}")
    return pw, browser, ctx, page
```

- [ ] **Step 5: 提交**

```bash
git add src/browser.py
git commit -m "feat(browser): add storage_state save/load methods for preheat login"
```

---

## Task 2: 新增 PreheatManager

**Files:**
- Create: `src/preheat.py`

**前置参考:**
- `src/browser.py` Task 1 — BrowserManager.load_state() 的签名
- `src/coder.py` Task 3（即将创建）— CoderManager 的方法签名，提前知道接口以便 PreheatManager 调用
- `config.yaml` Task 6 — preheat 配置字段名

- [ ] **Step 1: 创建 src/preheat.py 骨架**

```python
"""预热登录与多实例并发管理"""
import logging
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any, Callable

from playwright.sync_api import sync_playwright

from src.browser import BrowserManager
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
            mgr = BrowserManager(self.config)
            page = mgr.get_page()
            login_mgr = LoginManager(page, self.config)
            if not login_mgr.login():
                logger.error("预热登录失败")
                mgr.close()
                return False
            logger.info("预热登录成功，保存登录态...")
            mgr.save_state(str(STATE_FILE))
            mgr.close()
            return True
        except Exception as e:
            logger.error(f"预热登录异常: {e}")
            return False

    # --- 启动多实例 ---
    def launch_instances(self, n: int = 3):
        """在 9:59:00 执行：启动 n 个浏览器实例，均加载 storage_state"""
        logger.info(f"启动 {n} 个抢购实例...")
        self.pw = sync_playwright().start()
        self.browser = self.pw.chromium.launch(
            headless=self.config.get('browser', {}).get('headless', False),
            args=['--disable-blink-features=AutomationControlled']
        )

        for i in range(n):
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
            # 每个实例间隔 10 秒启动（配置可调）
            if i < n - 1:
                interval = self.preheat_config.get('instance_launch_interval', 10)
                time.sleep(interval)

    # --- 并发抢购 ---
    def _instance_click(self, instance: BrowserInstance) -> Dict[str, Any]:
        """单个实例的高频抢购循环，运行在独立线程中"""
        result = {"success": False, "reason": "", "page": None, "instance_id": instance.id}
        try:
            coder = CoderManager(
                page=instance.page,
                config=self.config,
                test_mode=False,
                target_time=self._get_target_time(),
                stop_event=self.stop_event
            )
            # 提前开始检测（从配置读取 buffer 秒数，默认 5）
            click_result = coder.high_frequency_click(
                stop_event=self.stop_event,
                timeout=self.preheat_config.get('no_refresh_window', 20)
            )
            if click_result.get("success") and not self.success_event.is_set():
                with self.lock:
                    if not self.success_event.is_set():
                        self.success_event.set()
                        self.stop_event.set()
                        result = click_result
                        result["instance_id"] = instance.id
                        logger.info(f"实例 {instance.id} 抢购成功!")
                        return result
        except Exception as e:
            logger.error(f"实例 {instance.id} 异常: {e}")
            result["reason"] = str(e)
        return result

    def start_purchase_concurrent(self) -> Dict[str, Any]:
        """启动 n 个线程并发执行抢购，谁先成功返回谁的结果"""
        threads = []
        for inst in self.instances:
            t = threading.Thread(target=self._instance_click, args=(inst,))
            t.start()
            threads.append(t)
            time.sleep(0.2)  # 稍微错开启动顺序

        # 等待任一成功或全部结束
        for t in threads:
            t.join()

        # 如果没有任何成功，返回失败
        if not self.success_event.is_set():
            return {"success": False, "reason": "所有实例均未成功", "page": None}
        return self.winner_result if self.winner_result else {"success": False, "reason": "未获取到成功结果"}

    def cleanup(self):
        """关闭所有实例"""
        for inst in self.instances:
            try:
                inst.close()
            except Exception:
                pass
        if self.browser:
            try:
                self.browser.close()
            except Exception:
                pass
        if self.pw:
            try:
                self.pw.stop()
            except Exception:
                pass
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

- [ ] **Step 2: 提交**

```bash
git add src/preheat.py
git commit -m "feat: add PreheatManager for preheat login and multi-instance concurrency"
```

---

## Task 3: CoderManager 核心改造

**Files:**
- Modify: `src/coder.py`

**前置参考:**
- `src/scheduler.py:69-83` — 现有 `_wait_until` 方法逻辑
- `src/coder.py:85-210` — `_wait_for_purchase_button` 完整实现（需要彻底重写）

- [ ] **Step 1: 重写 __init__，新增 stop_event 参数**

将 `coder.py` 中的 `__init__` 方法改造：

```python
def __init__(self, page: Page, config: dict, test_mode: bool = False, target_time: datetime = None, stop_event=None):
    self.page = page
    self.config = config
    self.purchase_config = config.get('purchase', {})
    self.plan_type = self.purchase_config.get('plan_type', 'monthly')
    self.fallback_plan = self.purchase_config.get('fallback_plan', 'quarterly')
    self.test_mode = test_mode
    self.target_time = target_time
    self.stop_event = stop_event if stop_event else threading.Event()
```

（顶部需要 `import threading`）

- [ ] **Step 2: 删除 `_wait_for_purchase_button`，替换为 `high_frequency_click`**

将整个 `_wait_for_purchase_button` 方法（约120行）替换为新的实现：

```python
def high_frequency_click(self, stop_event: threading.Event, timeout: int = 20) -> Dict[str, Any]:
    """
    高频轮询点击模式，抢购窗口内不刷新页面。

    Args:
        stop_event: 共享停止事件，任一实例成功则全部停止
        timeout: 超时秒数（从开始检测算起）

    Returns:
        {"success": bool, "reason": str, "page": Page, "instance_id": int}
    """
    result = {"success": False, "reason": "", "page": self.page}

    selector_list = [
        'button:has-text("立即购买 ¥0")',
        'a:has-text("立即购买 ¥0")',
        'button:has-text("¥0")',
        'a:has-text("¥0")',
        'button:has-text("立即购买")',
        'a:has-text("立即购买")',
        '[class*="buy"]',
    ]

    start_time = time.time()
    last_log_time = 0
    last_button_check = start_time
    click_start_time = None
    button_available = False
    can_start_clicking = False
    target_time = self.target_time if self.target_time else self._get_target_time()

    # click_buffer: 提前多少秒开始检测（配置可调，默认 5 秒）
    click_buffer = self.purchase_config.get('click_buffer', 5)

    if self.test_mode:
        can_start_clicking = True
        logger.info("测试模式：立即开始高频检测")
    else:
        logger.info(f"目标抢购时间: {target_time}，提前 {click_buffer} 秒开始检测")

    # 等待到达目标时间
    while datetime.now() < target_time - timedelta(seconds=click_buffer):
        if stop_event.is_set():
            return {"success": False, "reason": "被其他实例抢先", "page": self.page}
        time.sleep(0.1)

    can_start_clicking = True
    logger.info("开始高频检测购买按钮...")

    while time.time() - start_time < timeout:
        if stop_event.is_set():
            return {"success": False, "reason": "被其他实例抢先", "page": self.page}

        # --- 找按钮 ---
        btn = None
        for selector in selector_list:
            try:
                count = self.page.locator(selector).count()
                if count > 0:
                    candidate = self.page.locator(selector).first
                    if candidate.is_visible():
                        btn = candidate
                        break
            except Exception:
                continue

        if btn is None:
            last_button_check = time.time()
            time.sleep(0.02)
            continue

        # --- 检查按钮状态 ---
        try:
            is_disabled = btn.get_attribute('disabled')
            btn_text = btn.inner_text()
        except Exception:
            time.sleep(0.02)
            continue

        if is_disabled is not None or '售罄' in btn_text or '售完' in btn_text:
            last_button_check = time.time()
            if time.time() - last_log_time > 5:
                logger.info(f"按钮暂不可用: {btn_text[:30]}...")
                last_log_time = time.time()
            click_start_time = None
            time.sleep(0.02)
            continue

        # --- 按钮可用！开始高频点击 ---
        if not button_available:
            button_available = True
            click_start_time = time.time()
            logger.info(f"检测到可用按钮: {btn_text[:30]}，开始高频点击...")

        # 高频点击持续 3 秒
        if click_start_time and time.time() - click_start_time < 3:
            try:
                btn.click(timeout=200, no_wait_after=True)
            except Exception as e:
                logger.debug(f"点击异常: {e}")
                button_available = False
                time.sleep(0.01)
                continue
            time.sleep(0.02)
        else:
            # 高频点击完成，验证是否成功
            logger.info("高频点击完成，验证结果...")
            if self._verify_click_success():
                result["success"] = True
                result["reason"] = "抢购成功"
                return result
            else:
                # 点击了但页面没跳转，继续尝试
                button_available = False
                click_start_time = time.time()

    logger.warning("高频点击超时，未检测到成功")
    result["reason"] = "超时未成功"
    return result
```

- [ ] **Step 3: 新增 `_verify_click_success` 方法**

在 `_confirm_order` 方法之后新增：

```python
def _verify_click_success(self) -> bool:
    """验证点击购买按钮后是否成功进入结算/支付流程"""
    try:
        # 检查 URL 是否跳转
        current_url = self.page.url.lower()
        logger.info(f"点击后 URL: {current_url}")

        # 检查是否有结算/支付相关元素
        indicators = [
            'text=确认订单',
            'text=提交订单',
            'text=去支付',
            'button:has-text("确认")',
            'button:has-text("提交")',
        ]
        for ind in indicators:
            if self.page.locator(ind).first.is_visible(timeout=1000):
                logger.info("检测到订单确认页面")
                return True
        return False
    except Exception as e:
        logger.debug(f"验证点击成功异常: {e}")
        return False
```

- [ ] **Step 4: 更新 `purchase` 方法，适配 stop_event**

将 `purchase()` 中的调用改为：

```python
clicked = self.high_frequency_click(
    stop_event=self.stop_event,
    timeout=self.purchase_config.get('end_after', 900) if not self.test_mode else 5
)
```

- [ ] **Step 5: 提交**

```bash
git add src/coder.py
git commit -m "feat(coder): rewrite to high-frequency click mode with stop_event coordination"
```

---

## Task 4: Scheduler 改造

**Files:**
- Modify: `src/scheduler.py`

**前置参考:**
- `src/preheat.py` Task 2 — PreheatManager 的方法签名
- `src/scheduler.py:24-56` — 现有 start() 完整方法（需要彻底重写）

- [ ] **Step 1: 重写 Scheduler.start()**

将 `scheduler.py` 中的 `start()` 方法替换为预热调度逻辑：

```python
def start(self):
    """启动预热调度器"""
    self.running = True
    preheat_config = self.config.get('preheat', {})
    if not preheat_config.get('enabled', True):
        logger.info("预热模式未启用，使用原有调度逻辑")
        self._start_legacy()
        return

    login_hour, login_min = self._parse_time(preheat_config.get('login_time', '09:55:00'))
    launch_hour, launch_min = self._parse_time('09:59:00')
    click_hour, click_min = self._parse_time('09:59:55')

    login_time = self._get_today_target(login_hour, login_min)
    launch_time = self._get_today_target(launch_hour, launch_min)
    click_time = self._get_today_target(click_hour, click_min)

    if datetime.now() >= login_time:
        login_time = login_time + timedelta(days=1)
        launch_time = launch_time + timedelta(days=1)
        click_time = click_time + timedelta(days=1)

    logger.info(f"预热调度已启动:")
    logger.info(f"  预热登录: {login_time}")
    logger.info(f"  启动实例: {launch_time}")
    logger.info(f"  开始抢购: {click_time}")

    while self.running:
        now = datetime.now()

        # 阶段1: 等待预热时间
        if now < login_time:
            logger.info(f"等待预热登录: {login_time}")
            self._wait_until(login_time)
            if not self.running:
                break

            from src.preheat import PreheatManager
            preheat = PreheatManager(self.config)
            if not preheat.preheat_login():
                logger.error("预热登录失败，跳过今日抢购，等待明天")
                time.sleep(3600)
                login_time += timedelta(days=1)
                launch_time += timedelta(days=1)
                click_time += timedelta(days=1)
                continue

            # 阶段2: 等待启动时间
            if not self.running:
                break
            logger.info(f"等待启动实例: {launch_time}")
            self._wait_until(launch_time)
            if not self.running:
                break

            n_instances = preheat_config.get('instances', 3)
            preheat.launch_instances(n=n_instances)

            # 阶段3: 等待抢购开始
            if not self.running:
                break
            logger.info(f"等待开始抢购: {click_time}")
            self._wait_until(click_time)
            if not self.running:
                break

            # 阶段4: 并发抢购
            logger.info("开始并发抢购...")
            result = preheat.start_purchase_concurrent()

            # 阶段5: 支付
            if result.get("success") and result.get("page"):
                logger.info("进入支付流程...")
                payment_mgr = PaymentManager(result["page"], self.config)
                payment_result = payment_mgr.handle_payment(result)
                if payment_result.get("success"):
                    logger.info("支付成功!")
                else:
                    logger.warning(f"支付未完成: {payment_result.get('reason')}")
            else:
                logger.warning(f"抢购未成功: {result.get('reason', 'unknown')}")

            # 清理
            preheat.cleanup()
            logger.info("本次抢购结束，等待明天...")

            # 更新为明天的时间
            time.sleep(300)
            login_time += timedelta(days=1)
            launch_time += timedelta(days=1)
            click_time += timedelta(days=1)
```

- [ ] **Step 2: 新增辅助方法**

在 Scheduler 类中添加：

```python
def _parse_time(self, time_str: str):
    """解析 'HH:MM:SS' 格式"""
    parts = time_str.split(':')
    return int(parts[0]), int(parts[1])

def _get_today_target(self, hour: int, minute: int) -> datetime:
    """构建今天指定时间点"""
    now = datetime.now()
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)
```

- [ ] **Step 3: 提交**

```bash
git add src/scheduler.py
git commit -m "feat(scheduler): rewrite to preheat+concurrent purchase mode"
```

---

## Task 5: main.py 适配新调用链

**Files:**
- Modify: `main.py`

**前置参考:**
- `src/scheduler.py` Task 4 — Scheduler.start() 的新签名（无变化，但内部逻辑不同了）
- `src/preheat.py` Task 2 — PreheatManager.preheat_login() — main.py 的 test 模式可能需要适配

- [ ] **Step 1: 读取 main.py 确认当前调用方式**

确认 `run_purchase` 函数和 `run_scheduler` 函数的签名。

- [ ] **Step 2: 改造 main.py 的 run_purchase 函数（test 模式适配）**

Test 模式（`python main.py --mode test`）仍然需要单次完整执行，将其改造为直接使用 PreheatManager：

```python
def run_purchase(config: dict, debug: bool = False, test_mode: bool = False, target_time: datetime = None):
    """执行一次抢购（test 模式）"""
    from src.preheat import PreheatManager

    preheat = PreheatManager(config)
    try:
        # 预热登录
        if not preheat.preheat_login():
            logger.error("预热登录失败")
            return False

        # 启动实例
        n = config.get('preheat', {}).get('instances', 3)
        preheat.launch_instances(n=n)
        time.sleep(2)  # 等待页面稳定

        # 并发抢购
        result = preheat.start_purchase_concurrent()

        if result.get("success") and result.get("page"):
            payment_mgr = PaymentManager(result["page"], config)
            payment_result = payment_mgr.handle_payment(result)
            if payment_result.get("success"):
                logger.info("支付成功!")
            else:
                logger.warning(f"支付未完成: {payment_result.get('reason')}")
        else:
            logger.warning(f"抢购未成功: {result.get('reason', 'unknown')}")

        return result.get("success", False)
    finally:
        preheat.cleanup()
```

- [ ] **Step 3: 提交**

```bash
git add main.py
git commit -m "feat(main): adapt to PreheatManager for both test and subscribe modes"
```

---

## Task 6: config.yaml 新增预热配置

**Files:**
- Modify: `config.yaml`

**前置参考:**
- `config.yaml` 现有结构
- `src/preheat.py` Task 2 — PreheatManager 读取的字段名

- [ ] **Step 1: 更新 config.yaml**

在 `config.yaml` 中 `purchase` 段之后新增 `preheat` 段：

```yaml
# BigModel.cn 抢购配置

account:
  phone: "17368672935" # 手机号
  password: "521592659aSD" # 密码

purchase:
  hour: 10
  minute: 0
  start_before: 60 # 提前多少秒开始（已废弃，由 preheat.click_buffer 替代）
  end_after: 20 # 抢购窗口持续秒数（缩短为20秒，因为预热模式下页面已就绪）
  refresh_interval: 0.5 # 刷新间隔（秒，已废弃，抢购窗口内不刷新）
  plan_type: "monthly" # 首选套餐
  fallback_plan: "quarterly" # 售罄后降级

preheat:
  enabled: true           # 是否启用预热模式
  login_time: "09:55:00"  # 预热登录时间
  instances: 3             # 并发实例数
  instance_launch_interval: 10  # 实例启动间隔（秒）
  click_buffer: 5          # 提前开始高频检测的秒数

browser:
  headless: false
  screenshot: true

debug:
  save_html: true
  console_log: true
```

- [ ] **Step 2: 提交**

```bash
git add config.yaml
git commit -m "feat(config): add preheat section for concurrent purchase"
```

---

## Task 7: 移除废弃的 purchase.py

**Files:**
- Delete: `src/purchase.py`

**前置参考:**
- `main.py` — 确认 `PurchaseManager` 无引用
- `src/coder.py` — 确认 `CoderManager` 已独立承担抢购逻辑

- [ ] **Step 1: 确认无引用**

```bash
grep -r "PurchaseManager" E:/project/GLM_GET/src/ E:/project/GLM_GET/main.py
```

预期：无输出。

- [ ] **Step 2: 删除文件**

```bash
rm src/purchase.py
```

- [ ] **Step 3: 提交**

```bash
git rm src/purchase.py
git commit -m "chore: remove deprecated PurchaseManager"
```

---

## Task 8: 端到端验证

**Files:**
- 测试命令参考 `config.yaml`
- 截图输出到 `screenshots/`

- [ ] **Step 1: 运行 test 模式验证预热流程**

```bash
cd E:/project/GLM_GET
python main.py --mode test --debug
```

预期输出：
1. 09:55 预热登录流程（日志显示 `开始预热登录...` → `预热登录成功，保存登录态...`）
2. 启动3个实例（日志显示 `实例 0/1/2 启动成功`）
3. 高频检测（日志显示 `开始高频检测购买按钮...`）
4. test 模式5秒超时后退出，显示 `抢购未成功: 超时未成功` 或成功截图

- [ ] **Step 2: 检查截图输出**

```bash
ls -la screenshots/
```

预期：`screenshots/` 下有新截图文件。

- [ ] **Step 3: 检查 storage_state.json 生成**

```bash
ls -la storage_state.json
```

预期：文件存在且非空（登录态已保存）。

- [ ] **Step 4: 提交**

```bash
git add -A
git commit -m "test: verify preheat concurrent purchase end-to-end"
```

---

## 自我审查

- [ ] Spec 覆盖率检查：所有 spec 中的需求都有对应任务
- [ ] 占位符扫描：无 TBD/TODO/模糊描述
- [ ] 类型一致性：
  - `PreheatManager.__init__` 中 `stop_event` 类型为 `threading.Event`
  - `CoderManager.high_frequency_click(stop_event, timeout)` 签名一致
  - `PreheatManager._instance_click` 正确传递 `stop_event`
  - `Scheduler.start()` 中 `preheat.preheat_login()` / `launch_instances()` / `start_purchase_concurrent()` / `cleanup()` 方法名与 Task 2 定义一致
- [ ] 无循环依赖：coder.py 不依赖 preheat.py，preheat.py 依赖 coder.py（可接受）
