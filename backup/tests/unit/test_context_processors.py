"""Unit tests for the app_info context processor."""

import importlib.metadata
from unittest.mock import patch

from backup.context_processors import _get_app_info


class TestGetAppInfo:
    """Tests for _get_app_info(). The lru_cache is cleared around each case."""

    def setup_method(self):
        _get_app_info.cache_clear()

    def teardown_method(self):
        _get_app_info.cache_clear()

    def test_package_not_found_returns_dev_version(self, monkeypatch):
        """A missing package distribution should fall back to version 'dev'."""
        monkeypatch.delenv("GIT_COMMIT_SHORT", raising=False)
        monkeypatch.delenv("GIT_COMMIT", raising=False)

        with (
            patch(
                "backup.context_processors.importlib.metadata.version",
                side_effect=importlib.metadata.PackageNotFoundError,
            ),
            patch("backup.context_processors.subprocess.check_output", return_value=b"abc1234"),
        ):
            info = _get_app_info()

        assert info["version"] == "dev"

    def test_git_commit_short_takes_precedence(self, monkeypatch):
        """GIT_COMMIT_SHORT should win over GIT_COMMIT[:7]."""
        monkeypatch.setenv("GIT_COMMIT_SHORT", "short99")
        monkeypatch.setenv("GIT_COMMIT", "fulllongsha1234567")

        info = _get_app_info()

        assert info["commit"] == "short99"

    def test_git_commit_truncated_to_seven_when_no_short(self, monkeypatch):
        """Without GIT_COMMIT_SHORT, GIT_COMMIT should be truncated to 7 chars."""
        monkeypatch.delenv("GIT_COMMIT_SHORT", raising=False)
        monkeypatch.setenv("GIT_COMMIT", "abcdef1234567")

        info = _get_app_info()

        assert info["commit"] == "abcdef1"

    def test_subprocess_file_not_found_yields_empty_commit(self, monkeypatch):
        """When git is unavailable (FileNotFoundError), commit is '' with no exception."""
        monkeypatch.delenv("GIT_COMMIT_SHORT", raising=False)
        monkeypatch.delenv("GIT_COMMIT", raising=False)

        with patch(
            "backup.context_processors.subprocess.check_output",
            side_effect=FileNotFoundError("git not found"),
        ):
            info = _get_app_info()

        assert info["commit"] == ""
