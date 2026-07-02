"""Unit tests for the discover_instances management command wrapper."""

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command

DISCOVER = "backup.management.commands.discover_instances.discover_instances_from_env"
CHECK = "backup.management.commands.discover_instances.check_connections"


def _empty_result(**overrides):
    result = {"created": [], "skipped": [], "updated": [], "removed": []}
    result.update(overrides)
    return result


class TestDiscoverInstancesCommand:
    """Tests for the discover_instances CLI wrapper."""

    def test_force_flag_propagates(self):
        """--force should pass force=True to discover_instances_from_env."""
        with (
            patch(DISCOVER, return_value=_empty_result()) as mock_discover,
            patch(CHECK, return_value={}),
        ):
            call_command("discover_instances", "--force", stdout=StringIO())

        mock_discover.assert_called_once_with(force=True)

    def test_default_passes_force_false(self):
        """Without --force, force=False should be passed."""
        with (
            patch(DISCOVER, return_value=_empty_result()) as mock_discover,
            patch(CHECK, return_value={}),
        ):
            call_command("discover_instances", stdout=StringIO())

        mock_discover.assert_called_once_with(force=False)

    def test_skip_check_does_not_call_check_connections(self):
        """--skip-check should short-circuit before check_connections."""
        with (
            patch(DISCOVER, return_value=_empty_result()),
            patch(CHECK) as mock_check,
        ):
            call_command("discover_instances", "--skip-check", stdout=StringIO())

        mock_check.assert_not_called()

    def test_default_calls_check_connections(self):
        """The default path should run check_connections."""
        with (
            patch(DISCOVER, return_value=_empty_result()),
            patch(CHECK, return_value={}) as mock_check,
        ):
            call_command("discover_instances", stdout=StringIO())

        mock_check.assert_called_once()

    def test_output_formatting(self):
        """Created/skipped/removed and connection status lines should render as expected."""
        result = _empty_result(created=["PRIMARY"], skipped=["SECONDARY"], removed=["OLD"])
        out = StringIO()

        with (
            patch(DISCOVER, return_value=result),
            patch(CHECK, return_value={"PRIMARY": "ok", "SECONDARY": "unreachable"}),
        ):
            call_command("discover_instances", stdout=out)

        text = out.getvalue()
        assert "Removed instances: OLD" in text
        assert "Created instances: PRIMARY" in text
        assert "Skipped (already exist): SECONDARY" in text
        # status icon: "ok" -> "OK", others -> upper()
        assert "PRIMARY: OK" in text
        assert "SECONDARY: UNREACHABLE" in text

    def test_no_env_vars_message(self):
        """An all-empty result should print the 'no env vars' message."""
        out = StringIO()

        with (
            patch(DISCOVER, return_value=_empty_result()),
            patch(CHECK, return_value={}),
        ):
            call_command("discover_instances", stdout=out)

        assert "No PIHOLE_* environment variables found" in out.getvalue()
