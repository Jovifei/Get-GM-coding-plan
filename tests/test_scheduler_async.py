"""Tests for async Scheduler"""
import pytest
import inspect
from src.scheduler import Scheduler


def test_scheduler_start_is_coroutine():
    assert inspect.iscoroutinefunction(Scheduler.start)
    assert inspect.iscoroutinefunction(Scheduler._wait_until)
