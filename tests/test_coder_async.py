"""Tests for async CoderManager with no_refresh_window"""
import pytest
import inspect
from datetime import datetime, timedelta
from src.coder import CoderManager, should_skip_refresh


def test_coder_methods_are_coroutines():
    assert inspect.iscoroutinefunction(CoderManager.high_frequency_click)
    assert inspect.iscoroutinefunction(CoderManager._refresh_for_retry_if_needed)
    assert inspect.iscoroutinefunction(CoderManager._select_subscription_period)
    assert inspect.iscoroutinefunction(CoderManager._verify_click_success)
    assert inspect.iscoroutinefunction(CoderManager.purchase)
    assert inspect.iscoroutinefunction(CoderManager._select_plan)
    assert inspect.iscoroutinefunction(CoderManager._confirm_order)


def test_should_skip_refresh_in_no_refresh_window():
    target = datetime(2026, 5, 12, 10, 0, 0)
    no_refresh_window = 20

    # 09:59:40 — inside window
    now = datetime(2026, 5, 12, 9, 59, 40)
    assert should_skip_refresh(now, target, no_refresh_window) is True

    # 09:59:39 — outside window
    now = datetime(2026, 5, 12, 9, 59, 39)
    assert should_skip_refresh(now, target, no_refresh_window) is False

    # 10:00:20 — outside window (boundary)
    now = datetime(2026, 5, 12, 10, 0, 20)
    assert should_skip_refresh(now, target, no_refresh_window) is False

    # 10:00:19 — inside window
    now = datetime(2026, 5, 12, 10, 0, 19)
    assert should_skip_refresh(now, target, no_refresh_window) is True


def test_should_skip_refresh_no_window():
    target = datetime(2026, 5, 12, 10, 0, 0)
    now = datetime(2026, 5, 12, 9, 59, 50)
    assert should_skip_refresh(now, target, no_refresh_window=0) is False
