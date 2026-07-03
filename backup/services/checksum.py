"""Shared checksum utilities for backup files."""

import hashlib
from pathlib import Path


def calculate_checksum(filepath: Path) -> str:
    """Calculate the SHA256 checksum of a file, reading it in chunks."""
    sha256 = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            sha256.update(chunk)
    return sha256.hexdigest()
