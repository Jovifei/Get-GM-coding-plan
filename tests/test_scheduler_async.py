"""Tests for async Scheduler"""
from datetime import datetime

import inspect
import pytest

from src.scheduler import Scheduler, resolve_sale_at


def test_resolve_sale_at_uses_ref_date():
    ref = datetime(2026, 5, 14, 9, 58, 30)
    pc = {"hour": 10, "minute": 0, "second": 0}
    assert resolve_sale_at(ref, pc) == datetime(2026, 5, 14, 10, 0, 0)


def test_resolve_sale_at_respects_second():
    ref = datetime(2026, 5, 1, 0, 0, 0)
    pc = {"hour": 10, "minute": 30, "second": 15}
    assert resolve_sale_at(ref, pc) == datetime(2026, 5, 1, 10, 30, 15)


def test_scheduler_start_is_coroutine():
    assert inspect.iscoroutinefunction(Scheduler.start)
    assert inspect.iscoroutinefunction(Scheduler._wait_until)
