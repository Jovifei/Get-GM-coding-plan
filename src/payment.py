"""支付模块"""
import logging
import time
from typing import Dict, Any, Optional

from playwright.sync_api import Page

from src.diagnostics import diagnostic_step

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
            with diagnostic_step(logger, "尝试余额支付"):
                balance_paid = self._try_balance_pay()
            if balance_paid:
                result["success"] = True
                result["reason"] = "余额支付成功"
                return result

            # 余额不足，获取扫码支付链接
            logger.info("余额不足，获取扫码支付...")
            with diagnostic_step(logger, "获取扫码支付信息"):
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
