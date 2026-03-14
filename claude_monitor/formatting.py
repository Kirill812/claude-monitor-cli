"""Terminal output formatting utilities."""

import sys
from datetime import datetime, timezone

COLORS = {
    "reset": "\033[0m",
    "bold": "\033[1m",
    "dim": "\033[2m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "magenta": "\033[35m",
    "cyan": "\033[36m",
    "white": "\033[37m",
}


def c(text, color):
    """Colorize text for terminal output."""
    if not sys.stdout.isatty():
        return str(text)
    return f"{COLORS.get(color, '')}{text}{COLORS['reset']}"


def ts_to_str(ts_ms):
    """Convert millisecond timestamp to readable local time string."""
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).astimezone()
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def relative_time(ts_ms):
    """Convert millisecond timestamp to relative time string like '5m ago'."""
    now = datetime.now().timestamp() * 1000
    diff_s = (now - ts_ms) / 1000
    if diff_s < 60:
        return f"{int(diff_s)}s ago"
    elif diff_s < 3600:
        return f"{int(diff_s / 60)}m ago"
    elif diff_s < 86400:
        return f"{int(diff_s / 3600)}h ago"
    else:
        return f"{int(diff_s / 86400)}d ago"


def sanitize_display(text, max_len=80):
    """Truncate and redact sensitive content from display text."""
    if "eyJ" in text or "token" in text.lower():
        return c("[redacted - contains token]", "red")
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text
