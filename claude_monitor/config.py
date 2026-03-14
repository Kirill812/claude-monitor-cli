"""Paths and constants."""

from pathlib import Path

CLAUDE_DIR = Path.home() / ".claude"
HISTORY_FILE = CLAUDE_DIR / "history.jsonl"
SESSIONS_DIR = CLAUDE_DIR / "sessions"
FILE_HISTORY_DIR = CLAUDE_DIR / "file-history"
