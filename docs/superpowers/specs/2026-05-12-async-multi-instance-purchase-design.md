# 异步多实例并行抢购 - 设计文档

日期: 2026-05-12
状态: 已确认

## 问题分析

### 核心缺陷
1. **只有1个实例执行购买** — `use_threads: false` 时 `start_purchase_concurrent()` 直接返回实例0的结果，实例1/2 被忽略
2. **无 `no_refresh_window` 实现** — 配置声明但代码未实现，10:00 关键时刻仍在刷新页面
3. **刷新间隔过长** — 1.5s 刷新间隔可能导致错过放货瞬间
4. **Playwright Sync API 限制** — 无法跨线程运行，当前"并发"方案是顺序执行

### 日志分析
- 登录正常（09:55:14 成功）
- 3个实例启动成功（09:57:36 完成）
- 09:58:00 开始检测，按钮始终为"抢购人数过多/暂时售罄"
- 10:00:45 按钮变为"特惠订阅"，被当作不可用处理
- 10:20:00 超时退出，从未成功点击

## 设计方案

### 架构变更

```
当前: 实例0 → 点击 → 失败 → 结束（实例1/2从未执行）
改进: 实例0 ─┐
       实例1 ─┼→ asyncio.gather() 同时高频点击 → 谁先成功谁通知其他停止
       实例2 ─┘
```

### 改动范围

#### 1. coder.py — 核心购买逻辑
- `high_frequency_click()` 改为 `async def`
- 所有 `page.click()` / `page.reload()` / `page.query_selector_all()` 改为 `await`
- 新增 `no_refresh_window` 逻辑：09:59:40 ~ 10:00:20 禁止刷新
- 刷新间隔从 1.5s 降到 0.8s（非关键窗口期）
- 10:00:00 前10秒进入"冲刺模式"：停止刷新，只高频检测
- 点击成功检测改为 `page.wait_for_url()` 监听URL变化
- "特惠订阅" 状态也视为可购买信号

#### 2. preheat.py — 多实例管理
- `launch_instances()` 改为 `async def`
- `start_purchase_concurrent()` 改为 `async def`，使用 `asyncio.gather()` 并行执行3个实例
- 任何实例成功 → 通过 `asyncio.Event` 通知其他实例停止
- `preheat_login()` 改为 `async def`
- `cleanup()` 改为 `async def`

#### 3. browser.py — 浏览器管理
- `create_browser()` 改为 `async def`，使用 `playwright.async_api`
- 返回的 browser/context/page 全部为 async 版本

#### 4. login.py — 登录模块
- `login()` 改为 `async def`
- 所有 page 操作改为 `await`

#### 5. payment.py — 支付模块
- `handle_payment()` 改为 `async def`

#### 6. scheduler.py — 调度器
- 主调度循环改为 `async def`
- 使用 `asyncio.run()` 启动

#### 7. config.yaml — 配置优化
- `use_threads` 改为 `use_async`（或直接移除，因为 async 是唯一方案）
- 新增 `no_refresh_window: 20` 实际生效
- 刷新间隔 `refresh_interval` 从 1.5 改为 0.8

### 关键时间窗口策略

| 时间段 | 策略 |
|--------|------|
| 09:58:00 ~ 09:59:39 | 正常检测，每 0.8s 刷新一次 |
| 09:59:40 ~ 10:00:20 | **禁止刷新**，只检测按钮状态 |
| 10:00:00 ~ 10:00:20 | 冲刺模式：检测到可点击后 20ms 间隔疯狂点击 |
| 10:00:20 ~ 10:20:00 | 恢复正常检测，每 0.8s 刷新一次 |

### 依赖变更
- `requirements.txt`: 无需变更（playwright 已包含 async_api）

### 不改动的部分
- main.py 入口逻辑（仅适配 async 调用）
- config.py 配置加载
- diagnostics.py 日志工具
- tests/ 测试文件（后续更新）

## 验证标准
1. 3个实例在 09:58:00 同时开始检测（日志可见3个实例的输出交错）
2. 09:59:40 ~ 10:00:20 期间无页面刷新日志
3. 任何一个实例成功购买后，其他实例立即停止
4. 成功后自动进入支付流程
