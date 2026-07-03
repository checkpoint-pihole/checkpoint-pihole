"""Unit tests for the shared boolean env parser."""

import pytest

from config.env import get_bool_env


@pytest.mark.parametrize("value", ["true", "True", "TRUE", "1", "yes", "YES", "Yes"])
def test_truthy_values(monkeypatch, value):
    """All accepted spellings parse as True."""
    monkeypatch.setenv("SOME_FLAG", value)
    assert get_bool_env("SOME_FLAG") is True


@pytest.mark.parametrize("value", ["false", "0", "no", "off", "", "banana"])
def test_falsy_values(monkeypatch, value):
    """Anything not in the accepted set parses as False."""
    monkeypatch.setenv("SOME_FLAG", value)
    assert get_bool_env("SOME_FLAG") is False


def test_default_used_when_unset(monkeypatch):
    """The default applies when the variable is absent."""
    monkeypatch.delenv("SOME_FLAG", raising=False)
    assert get_bool_env("SOME_FLAG", True) is True
    assert get_bool_env("SOME_FLAG", False) is False


def test_notifications_reexport_is_same_helper():
    """notifications.config re-exports the shared helper (no divergent copy)."""
    from backup.services.notifications.config import get_bool_env as notif_get_bool_env

    assert notif_get_bool_env is get_bool_env
