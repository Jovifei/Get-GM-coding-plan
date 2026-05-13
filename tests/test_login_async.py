"""Tests for async LoginManager"""
import pytest
import inspect
from src.login import LoginManager


def test_login_methods_are_coroutines():
    assert inspect.iscoroutinefunction(LoginManager.login)
    assert inspect.iscoroutinefunction(LoginManager._login_by_account)
    assert inspect.iscoroutinefunction(LoginManager._login_by_code)
    assert inspect.iscoroutinefunction(LoginManager.is_logged_in)
    assert inspect.iscoroutinefunction(LoginManager._print_page_info)
