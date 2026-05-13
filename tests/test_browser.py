"""Tests for async BrowserManager"""
import pytest
import inspect
from src.browser import BrowserManager


def test_browser_manager_launch_is_coroutine():
    assert inspect.iscoroutinefunction(BrowserManager._launch)
    assert inspect.iscoroutinefunction(BrowserManager.close)
    assert inspect.iscoroutinefunction(BrowserManager.take_screenshot)
    assert inspect.iscoroutinefunction(BrowserManager.save_html)
    assert inspect.iscoroutinefunction(BrowserManager.save_state)
    assert inspect.iscoroutinefunction(BrowserManager.load_state)


def test_browser_manager_get_page_stays_sync():
    """get_page should remain sync (just returns stored reference)"""
    assert not inspect.iscoroutinefunction(BrowserManager.get_page)


@pytest.mark.asyncio
async def test_browser_manager_launch_and_close():
    config = {
        'browser': {'headless': True, 'screenshot': False}
    }
    mgr = BrowserManager(config)
    await mgr._launch()
    page = mgr.get_page()
    assert page is not None
    await mgr.close()
