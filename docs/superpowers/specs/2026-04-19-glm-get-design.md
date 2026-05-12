# GLM_GET 规格文档

## 项目概述

**名称：** GLM_GET
**功能：** BigModel.cn GLM Coding Lite 套餐自动抢购
**类型：** 浏览器自动化脚本

## 抢购目标

- **目标页面：** <https://bigmodel.cn/glm-coding>
- **目标套餐：** GLM Coding Lite（连续包月 / 连续包季）
- **抢购时间：** 每日 10:00 准点
- **抢购窗口：** 9:59:00 - 10:15:00（共16分钟）

## 套餐优先级

1. 优先连续包月（monthly）
2. 售罄则降级连续包季（quarterly）

## 功能范围

### 必须实现

- [x] Playwright 浏览器管理（启动/关闭/截图）
- [x] 登录模块（手机号+密码 / 手机号+验证码）
- [x] 抢购核心（检测按钮、点击购买、选择套餐）
- [x] 支付流程（余额自动扣 / 扫码支付链接生成）
- [x] 定时调度（9:59开始，10:15结束）
- [x] 配置管理（config.yaml）

### 后续添加（通知模块）

- [ ] 飞书 webhook 通知
- [ ] 邮件 SMTP 通知

## 抢购流程

```
1. scheduler 9:59:00 触发
2. browser 启动浏览器，打开 GLM Coding 页面
3. login 执行登录（优先密码，失败可切换验证码）
4. 循环检测页面状态：
   - 检测是否有"立即购买"按钮
   - 10:00 之前按钮不可点击，等待
   - 10:00 准点，点击按钮
   - 10:00 - 10:15 内即使售罄也要循环点击购买按钮
5. 进入结算页，选择"连续包月"或降级"连续包季"
6. 尝试余额支付：
   - 余额充足 → 等待支付结果
   - 余额不足/扫码 → 生成支付链接/二维码
7. 每步记录日志
```

## 模块设计

### src/browser.py

**职责：** Playwright 浏览器生命周期管理

```
- launch(): 启动浏览器
- get_page(): 获取页面对象
- take_screenshot(name): 截图保存
- close(): 关闭浏览器
```

### src/login.py

**职责：** 登录 BigModel.cn

```
- login_by_password(phone, password): 密码登录
- login_by_code(phone, code): 验证码登录
- is_logged_in(): 检查登录状态
```

### src/coder.py

**职责：** 抢购核心逻辑

```
- wait_for_purchase_button(timeout): 等待购买按钮
- click_purchase(): 点击立即购买
- select_plan(plan_type): 选择套餐（monthly/quarterly）
- confirm_order(): 确认订单
```

### src/payment.py

**职责：** 支付处理

```
- try_balance_pay(): 尝试余额支付
- get_qrcode_url(): 获取扫码支付链接
- wait_for_payment(timeout): 等待支付回调
```

### src/scheduler.py

**职责：** 定时调度

```
- start(): 启动调度器
- _run_purchase(): 执行抢购
- _should_retry(): 判断是否在重试窗口内
```

### src/config.py

**职责：** 配置加载验证

```
- load(): 加载并验证 config.yaml
- get(key, default): 获取配置项
```

## 关键时序

| 时间 | 动作 |
|------|------|
| 9:59:00 | 开始刷新页面 |
| 10:00:00 | 准点检测购买按钮 |
| 10:00:00 - 10:15:00 | 循环抢购+重试 |
| 10:15:00 | 超时，结束抢购 |

## 配置项

### config.yaml

```yaml
account:
  phone: ""      # 手机号
  password: ""  # 密码

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

## 错误处理

| 场景 | 处理方式 |
|------|----------|
| 登录失败 | 重试3次，失败则退出发邮件通知 |
| 页面加载失败 | 刷新重试 |
| 购买按钮不存在 | 继续轮询 |
| 支付失败 | 记录支付链接，通知人工处理 |
| 超时（10:15） | 发送失败通知，退出 |

## 依赖

```
playwright>=1.40.0
pyyaml>=6.0
python-dateutil>=2.8.2
```

## 运行方式

```bash
# 每日定时抢购（默认）
python main.py

# 测试模式（立即执行）
python main.py --mode test

# 调试模式
python main.py --mode test --debug
```

## 文件结构

```
GLM_GET/
├── main.py
├── config.yaml
├── requirements.txt
├── docs/
│   └── specs/
│       └── 2026-04-19-glm-get-design.md
└── src/
    ├── __init__.py
    ├── browser.py
    ├── login.py
    ├── coder.py
    ├── payment.py
    ├── scheduler.py
    └── config.py
```
