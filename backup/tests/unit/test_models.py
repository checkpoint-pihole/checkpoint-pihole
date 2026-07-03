"""Unit tests for PiholeConfig model validation and constraints."""

from datetime import time

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from backup.models import PiholeConfig


@pytest.mark.django_db
class TestPiholeConfigEnvPrefixValidation:
    """Tests for the env_prefix RegexValidator."""

    @pytest.mark.parametrize(
        "bad_prefix",
        [
            "lower",  # lowercase not allowed
            "1ABC",  # must start with a letter
            "HAS-DASH",  # dashes not allowed
        ],
    )
    def test_invalid_env_prefix_raises_validation_error(self, bad_prefix):
        """full_clean should reject env_prefix values that violate the regex."""
        config = PiholeConfig(name="Test", env_prefix=bad_prefix, backup_time=time(3, 0))

        with pytest.raises(ValidationError) as exc_info:
            config.full_clean()

        assert "env_prefix" in exc_info.value.message_dict

    @pytest.mark.parametrize("good_prefix", ["PRIMARY", "A", "SITE_2", "NODE9"])
    def test_valid_env_prefix_passes_validation(self, good_prefix):
        """full_clean should accept env_prefix values that match the regex."""
        config = PiholeConfig(name="Test", env_prefix=good_prefix, backup_time=time(3, 0))
        # Should not raise
        config.full_clean()


@pytest.mark.django_db
class TestPiholeConfigEnvPrefixUniqueness:
    """Tests for the env_prefix unique constraint."""

    def test_duplicate_env_prefix_raises_integrity_error(self):
        """A second config with the same env_prefix must hit the DB unique constraint."""
        PiholeConfig.objects.create(name="First", env_prefix="DUPLICATE", backup_time=time(3, 0))

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                PiholeConfig.objects.create(name="Second", env_prefix="DUPLICATE", backup_time=time(3, 0))
