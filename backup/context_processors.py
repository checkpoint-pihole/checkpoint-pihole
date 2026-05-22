"""Template context processors for Checkpoint Pi-hole."""

import functools
import importlib.metadata
import os
import subprocess


@functools.lru_cache(maxsize=1)
def _get_app_info():
    """Get app version and build metadata (cached for process lifetime)."""
    try:
        version = importlib.metadata.version("checkpoint-pihole")
    except importlib.metadata.PackageNotFoundError:
        version = "dev"

    # Prefer GIT_COMMIT_SHORT, then truncate GIT_COMMIT, then git CLI
    commit_short = os.environ.get("GIT_COMMIT_SHORT", "")
    if not commit_short:
        commit_full = os.environ.get("GIT_COMMIT", "")
        if commit_full:
            commit_short = commit_full[:7]

    if not commit_short:
        try:
            commit_short = (
                subprocess.check_output(
                    ["git", "rev-parse", "--short", "HEAD"],
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                )
                .decode()
                .strip()
            )
        except Exception:
            commit_short = ""

    return {
        "version": version,
        "commit": commit_short,
        "build_date": os.environ.get("BUILD_DATE", ""),
        "build_ref": os.environ.get("BUILD_REF", ""),
    }


def app_info(request):
    """Add app version and build metadata to template context."""
    info = _get_app_info()
    return {
        "app_version": info["version"],
        "git_commit": info["commit"],
        "build_date": info["build_date"],
        "build_ref": info["build_ref"],
    }
