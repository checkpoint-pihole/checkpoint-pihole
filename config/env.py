"""Environment variable parsing helpers shared across settings and app code."""

import os

_TRUE_VALUES = ("true", "1", "yes")


def get_bool_env(key: str, default: bool = False) -> bool:
    """Parse a boolean environment variable.

    Accepts "true"/"1"/"yes" (case-insensitive) as True. Kept as a single
    helper so every boolean flag in the app agrees on what counts as true —
    a divergent parser on a security flag (e.g. VERIFY_SSL) can silently
    weaken TLS when a user writes "1" expecting it to work like the others.
    """
    return os.getenv(key, str(default)).lower() in _TRUE_VALUES
