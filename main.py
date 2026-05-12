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
from src.diagnostics import diagnostic_step, init_diagnostics
from src.payment import PaymentManager
from src.scheduler import Scheduler

# 日志配置
from pathlib import Path

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


def run_purchase(config: dict, debug: bool = False, test_mode: bool = False, target_time: datetime = None):
    """执行一次抢购（test 模式）"""
    from src.preheat import PreheatManager

    preheat = PreheatManager(config)
    try:
        # 预热登录
        with diagnostic_step(logger, "测试模式-预热登录"):
            login_ok = preheat.preheat_login()
        if not login_ok:
            logger.error("预热登录失败")
            return False

        # 启动实例
        n = config.get('preheat', {}).get('instances', 3)
        with diagnostic_step(logger, f"测试模式-启动{n}个抢购实例"):
            preheat.launch_instances(n=n)
        time.sleep(2)  # 等待页面稳定

        # 并发抢购
        with diagnostic_step(logger, "测试模式-并发抢购"):
            result = preheat.start_purchase_concurrent()

        if result.get("success") and result.get("page"):
            with diagnostic_step(logger, "测试模式-支付处理"):
                payment_mgr = PaymentManager(result["page"], config)
                payment_result = payment_mgr.handle_payment(result)
            if payment_result.get("success"):
                logger.info("支付成功!")
            else:
                logger.warning(f"支付未完成: {payment_result.get('reason')}")
        else:
            logger.warning(f"抢购未成功: {result.get('reason', 'unknown')}")

        with diagnostic_step(logger, "测试模式-保存结果截图"):
            browser_mgr = BrowserManager(config)
            browser_mgr.take_screenshot("result")
        return result.get("success", False)
    finally:
        with diagnostic_step(logger, "测试模式-清理资源"):
            preheat.cleanup()


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
    diagnostic_path = init_diagnostics(log_dir)
    logger.info(f"诊断日志文档: {diagnostic_path}", extra={"step": "diagnostics"})

    if args.debug:
        config['browser']['headless'] = False
        config['debug']['console_log'] = True

    logger.info(f"启动 GLM 抢购脚本 - 模式: {args.mode}")

    if args.mode == 'test':
        run_purchase(config, debug=True, test_mode=True)
    else:
        run_scheduler(config)


if __name__ == "__main__":
    main()
