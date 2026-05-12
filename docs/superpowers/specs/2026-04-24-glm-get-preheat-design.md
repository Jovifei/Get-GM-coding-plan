# GLM_GET 预热并发抢购设计

## 背景

GLM Coding Lite 免费套餐为秒杀场景（几秒内抢光），当前脚本的"冷启动"模式（每次失败重启浏览器+重新登录，耗时15秒）完全无法应对。需要改造为**预热并发**模式。

## 目标

- 消除抢购路径中的登录延迟（15秒→0秒）
- 同一账号多开3个浏览器实例并发抢购
- 抢购窗口内不再刷新页面，纯高频轮询点击
- 提前5秒进入检测状态，覆盖更广时间窗口

## 核心设计：预热并发架构

### 时序安排（每日 10:00 抢购）

| 时间 | 动作 |
|---|---|
| **9:55:00** | 启动主浏览器，完成登录，保存 `storage_state.json`，关闭浏览器 |
| **9:59:00** | 启动3个实例，均加载 `storage_state.json`（免登录），各自打开 GLM Coding 页并保持就绪 |
| **9:59:55** | 三个实例同时进入高频检测模式（每 0.02s 轮询按钮状态），**不再刷新页面** |
| **10:00:00** | 按钮变为"立即购买"的极短窗口内，三个实例同时尝试点击 |
| **首个成功** | 其余两个实例立即停止，成功实例进入 `_select_plan` + `_confirm_order` + 支付流程 |

### 架构图

```
9:55:00
  └─> Scheduler.start_preheat()
        └─> BrowserManager.launch() → LoginManager.login()
        └─> BrowserManager.save_state("storage_state.json")
        └─> BrowserManager.close()  ← 预热完成，关闭预热浏览器

9:59:00
  └─> PreheatManager.launch_instances(n=3)
        ├─> instance_1: new_context(storage_state) → new_page() → goto(glm-coding)
        ├─> instance_2: new_context(storage_state) → new_page() → goto(glm-coding)
        └─> instance_3: new_context(storage_state) → new_page() → goto(glm-coding)
        ← 三个页面保持打开，各自 networkidle

9:59:55
  └─> PreheatManager.start_purchase_concurrent()
        ├─> Thread-1: CoderManager(instance_1).high_frequency_click()
        ├─> Thread-2: CoderManager(instance_2).high_frequency_click()
        └─> Thread-3: CoderManager(instance_3).high_frequency_click()
        ← 共享 threading.Event(stop_event)，谁先成功谁 signal

成功/超时
  └─> PreheatManager.stop_instances()
        ├─> 成功实例：继续支付流程
        └─> 失败实例：关闭 context
        ← 所有实例关闭，释放资源
```

## 组件改造

### 1. BrowserManager（`src/browser.py`）

新增方法：
- `save_state(path: str)`：将当前 context 的 storage_state 保存到文件
- `load_state(path: str) -> BrowserContext`：从文件加载 storage_state 创建新 context

### 2. 新增 PreheatManager（`src/preheat.py`）

职责：
- 预热登录（9:55）
- 管理3个浏览器实例的启动/销毁/协调
- 并发抢购调度

关键属性：
```python
self.stop_event = threading.Event()      # 任一实例成功 → 全部停止
self.success_event = threading.Event()   # 标记是否有实例成功
self.winner_result = {}                  # 成功实例的结果
self.lock = threading.Lock()             # 保护 winner_result
self.instances: list[BrowserInstance] = []
```

### 3. CoderManager（`src/coder.py`）改造

**改造点 A：抢购窗口内绝不刷新页面**
- 当前代码每5秒找不到按钮就 `page.reload()`
- 改造后：9:59:55 ~ 10:00:15 窗口内，找不到按钮直接继续 0.02s 轮询，不刷新

**改造点 B：提前5秒开始检测**
```python
# 提前 5 秒开始高频检测
if not self.test_mode and not can_start_clicking and target_time:
    buffer = timedelta(seconds=5)
    if datetime.now() >= (target_time - buffer):
        can_start_clicking = True
```

**改造点 C：传入 stop_event，收到信号立即停止**
```python
def high_frequency_click(self, stop_event: threading.Event, timeout: int) -> dict:
    while not stop_event.is_set() and time.time() - start_time < timeout:
        # 检测按钮...
        if button_available and not stop_event.is_set():
            btn.click()
            # 验证成功 → 设置 stop_event
            stop_event.set()
            return result
```

### 4. Scheduler（`src/scheduler.py`）改造

改造调度流程：
- 旧：`while running: wait_until(target_time) → run_purchase()`
- 新：`while running: wait_until(preheat_time) → preheat_and_purchase()`

`preheat_and_purchase()` 伪代码：
```python
def preheat_and_purchase(self):
    # 1. 预热登录
    preheat = PreheatManager(self.config)
    if not preheat.preheat_login():
        logger.error("预热登录失败，跳过今日抢购")
        return

    # 2. 等待到 9:59:00 启动实例
    self._wait_until(launch_time)
    preheat.launch_instances(n=3)

    # 3. 等待到 9:59:55 开始抢购
    self._wait_until(click_start_time)
    result = preheat.start_purchase_concurrent()

    # 4. 支付
    if result.get("success"):
        payment_mgr = PaymentManager(result["page"], self.config)
        payment_mgr.handle_payment(result)

    # 5. 清理
    preheat.cleanup()
```

### 5. 废弃 PurchaseManager

原 `src/purchase.py` 中的 `PurchaseManager` 已无人使用（`main.py` 调用的是 `CoderManager`），本次一并移除。

## 状态协调与错误处理

| 场景 | 处理 |
|---|---|
| 某个实例页面崩溃/导航错误 | 自动重启该实例（重新加载 storage_state + 重新打开页面），不影响其他实例 |
| 所有实例都找不到按钮（持续到 10:00:15） | 统一超时退出，记录日志，次日重试 |
| 某个实例成功点击但支付失败 | 成功实例继续支付流程，其他实例已停止，不受影响 |
| storage_state 过期/登录失效 | 预热阶段已验证，抢购阶段如失效则该实例标记失败 |

## 配置项扩展

```yaml
preheat:
  enabled: true           # 是否启用预热模式
  login_time: "09:55:00"  # 预热登录时间
  instances: 3            # 并发实例数
  instance_launch_interval: 10  # 实例启动间隔（秒）
  click_buffer: 5         # 提前开始点击的秒数

purchase:
  no_refresh_window: 20   # 抢购窗口内不刷新的秒数
```

## 文件变更

```
src/
├── browser.py      # 改造：新增预热 + storage_state 管理
├── preheat.py      # 新增：预热登录 + 多实例管理
├── purchase.py     # 移除：原 PurchaseManager 已废弃
├── coder.py        # 改造：抢购逻辑适配多实例并发
├── scheduler.py    # 改造：调度流程改为预热 + 并发抢购
└── main.py         # 改造：调用链适配

config.yaml         # 扩展：新增 preheat 配置段
```
