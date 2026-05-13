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
