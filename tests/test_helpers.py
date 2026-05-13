"""Tests for pure-logic helper functions in coder.py"""
from datetime import datetime


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
    assert is_ready_purchase_text("特惠订阅 - 抢购人数过多") is False


def test_is_ready_purchase_text_handles_subscription_variant():
    """特惠订阅 should be recognized as purchasable"""
    from src.coder import is_ready_purchase_text
    assert is_ready_purchase_text("特惠订阅") is True


def test_get_subscription_period_label():
    from src.coder import get_subscription_period_label
    assert get_subscription_period_label("monthly") == "连续包月"
    assert get_subscription_period_label("quarterly") == "连续包季"
    assert get_subscription_period_label("yearly") == "连续包年"
    assert get_subscription_period_label("unknown") == "连续包季"
