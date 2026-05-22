"""System-level service utilities for Checkpoint Pi-hole."""

import logging
import os

logger = logging.getLogger(__name__)


def is_scheduler_running() -> bool:
    """Check if the APScheduler process is running by scanning /proc.

    This approach doesn't require pgrep/procps to be installed,
    making it more portable for minimal Docker images.

    Returns:
        True if the scheduler process is found, False otherwise.
    """
    try:
        for pid in os.listdir("/proc"):
            if not pid.isdigit():
                continue
            try:
                cmdline_path = f"/proc/{pid}/cmdline"
                with open(cmdline_path, "rb") as f:
                    cmdline = f.read().decode("utf-8", errors="ignore")
                    if "runapscheduler" in cmdline:
                        return True
            except (FileNotFoundError, PermissionError):
                # Process may have exited or we don't have permission
                continue
        return False
    except Exception as e:
        logger.warning(f"Error checking scheduler status: {e}")
        return False
