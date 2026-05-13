"""Tests for async PreheatManager"""
import pytest
import inspect
from src.preheat import PreheatManager


def test_preheat_methods_are_coroutines():
    """Verify that key PreheatManager methods are async coroutines."""
    assert inspect.iscoroutinefunction(PreheatManager.preheat_login), \
        "preheat_login should be async"
    assert inspect.iscoroutinefunction(PreheatManager.launch_instances), \
        "launch_instances should be async"
    assert inspect.iscoroutinefunction(PreheatManager.start_purchase_concurrent), \
        "start_purchase_concurrent should be async"
    assert inspect.iscoroutinefunction(PreheatManager.cleanup), \
        "cleanup should be async"
    assert inspect.iscoroutinefunction(PreheatManager._instance_click), \
        "_instance_click should be async"


def test_browser_instance_close_is_async():
    """Verify BrowserInstance.close is async."""
    from src.preheat import BrowserInstance
    assert inspect.iscoroutinefunction(BrowserInstance.close), \
        "BrowserInstance.close should be async"


def test_preheat_uses_asyncio_event():
    """Verify PreheatManager uses asyncio.Event instead of threading.Event."""
    import asyncio
    config = {'preheat': {}}
    mgr = PreheatManager(config)
    assert isinstance(mgr.stop_event, asyncio.Event), \
        "stop_event should be asyncio.Event"
    assert isinstance(mgr.success_event, asyncio.Event), \
        "success_event should be asyncio.Event"


def test_preheat_no_threading_lock():
    """Verify PreheatManager no longer has threading Lock."""
    config = {'preheat': {}}
    mgr = PreheatManager(config)
    assert not hasattr(mgr, 'lock'), \
        "PreheatManager should not have a lock attribute"


def test_no_threading_import():
    """Verify preheat.py does not import threading."""
    import src.preheat as mod
    import inspect
    source = inspect.getsource(mod)
    assert 'import threading' not in source, \
        "preheat.py should not import threading"
