# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

GLM_GET - BigModel.cn GLM Coding 套餐自动抢购脚本

### 功能
- 自动登录 BigModel.cn
- 每日 10:00 定时抢购 GLM Coding Lite 套餐（连续包月/连续包季）
- 支持多种浏览器自动化操作

## 开发命令

### 安装依赖
```bash
pip install -r requirements.txt
```

### 运行脚本
```bash
# 每日 10:00 自动抢购（默认）
python main.py

# 指定运行模式
python main.py --mode test        # 测试模式（立即执行）
python main.py --mode subscribe   # 订阅模式（每日定时）
```

### 配置文件
编辑 `config.yaml` 设置：
- 登录凭证
- 抢购时间
- 套餐类型选择

## 架构

```
GLM_GET/
├── main.py           # 入口脚本
├── config.yaml       # 配置文件
├── src/
│   ├── browser.py    # 浏览器管理（Playwright）
│   ├── login.py      # 登录模块
│   ├── purchase.py   # 抢购逻辑
│   └── scheduler.py  # 定时调度
└── requirements.txt
```

## 关键设计

- 使用 Playwright 进行浏览器自动化
- 配置文件分离敏感信息
- 支持调试模式截图
- 异常重试机制
