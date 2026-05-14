# 每日抢购失败归因与开售时刻钉死 — 设计说明

**日期:** 2026-05-14  
**状态:** 已批准并实现（核心逻辑见 `src/scheduler.py`、`src/preheat.py`、`src/coder.py`）

## 背景与问题陈述

用户现象归类为 **A**：在开抢窗口内页面长期显示「暂时售罄 / 某日 10:00 补货」等不可买文案，脚本持续刷新与检测，最终在 `purchase.end_after` 截止后报 **「超时未成功」**，未进入支付页。

需要区分两类根因：

1. **站点与竞争**：库存极少，按钮在整段窗口内从未进入可点击文案；脚本行为符合预期。
2. **本地逻辑**：开售日 `target_time` 因「在已过当天 10:00:00 之后才首次计算」被 `_get_target_time` 推到 **次日**，导致检测窗口与真实放货日错位。

## 成功标准

1. 订阅预热路径下，**本场开售时刻**由调度器根据 **与 `click_time` 同一日历日** 确定，不依赖「调用瞬间是否已过 `purchase.hour:minute:second`」。
2. 高频检测在 **超时退出** 时输出可检索的 **归因摘要**（含 `sale_at`、窗口截止、是否曾出现可买文案、最后一次按钮文案截断）。
3. 提供单元测试覆盖 `resolve_sale_at` 的日期钉死行为。

## 架构与数据流

- **`resolve_sale_at(ref, purchase_config)`**（`src/scheduler.py`）：用参考时刻 `ref` 的 **年月日**，替换为配置中的 `hour/minute/second`，得到本场 `sale_at`。
- **`Scheduler.start`**：在 `_wait_until(click_time)` 之后计算 `sale_at = resolve_sale_at(click_time, purchase_config)`，打日志 `本轮开售时刻 sale_at=...`，调用 `preheat.start_purchase_concurrent(sale_at=sale_at)`。
- **`PreheatManager.start_purchase_concurrent(sale_at=None)`**：若传入 `sale_at` 则所有实例的 `CoderManager` 使用同一 `target_time`；若为 `None`（临时调用）则回退 `_get_target_time()`。
- **`CoderManager.high_frequency_click`**：超时返回 `reason="超时未成功"`，并设置 `detail` 字符串（`sale_at`、`deadline`、`saw_ready_button`、`last_button`）。

## 测试模式（`main.py --mode test`）

命令行测试应 **立即** 进入高频检测短窗口，避免在非 10 点时段误用「真实开售日」导致数小时空等。实现：`run_purchase` 将 `test_mode` 传入 `start_purchase_concurrent(..., coder_test_mode=...)`，由 `PreheatManager` 传给 `CoderManager(..., test_mode=coder_test_mode)`。订阅模式不传，保持 `False`。

## 非目标（YAGNI）

- 不保证一定抢到（库存、风控、网络不可控）。
- 不在本设计内引入 NTP 对时服务；若需可对日志增加「本地时间与 sale_at 差值」告警，留待后续。

## 验证

- `pytest tests/test_scheduler_async.py`（含 `resolve_sale_at`）。
- 手动：`python main.py --mode subscribe` 日志中在并发抢购前应出现 `本轮开售时刻 sale_at=...` 与 `并发抢购目标时间 target_time=...`，二者日历日应与当日预热一致。
