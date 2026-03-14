"""Data access layer for Claude Code artifacts."""

import json
import os
import subprocess
from pathlib import Path

from .config import FILE_HISTORY_DIR, HISTORY_FILE, SESSIONS_DIR


def get_sessions():
    """Get all session info from session JSON files."""
    sessions = {}
    if not SESSIONS_DIR.exists():
        return sessions
    for f in SESSIONS_DIR.iterdir():
        if f.suffix == ".json":
            try:
                data = json.loads(f.read_text())
                sid = data.get("sessionId", "")
                sessions[sid] = data
            except (json.JSONDecodeError, OSError):
                pass
    return sessions


def get_active_sessions():
    """Get sessions whose PID is still running."""
    sessions = get_sessions()
    active = []
    for sid, info in sessions.items():
        pid = info.get("pid")
        if pid and os.path.exists(f"/proc/{pid}"):
            active.append(info)
    return active


def get_history():
    """Parse the prompt history JSONL file."""
    entries = []
    if not HISTORY_FILE.exists():
        return entries
    for line in HISTORY_FILE.read_text().strip().split("\n"):
        if not line.strip():
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return entries


def get_file_changes(session_id=None):
    """Get file change records from file-history directory."""
    changes = []
    if not FILE_HISTORY_DIR.exists():
        return changes

    dirs = (
        [FILE_HISTORY_DIR / session_id] if session_id else FILE_HISTORY_DIR.iterdir()
    )

    for session_dir in dirs:
        if not session_dir.is_dir():
            continue
        sid = session_dir.name
        for fpath in session_dir.iterdir():
            name = fpath.name
            version = "v1"
            if "@" in name:
                parts = name.rsplit("@", 1)
                version = parts[1]
            stat = fpath.stat()
            changes.append(
                {
                    "session_id": sid,
                    "file": name,
                    "version": version,
                    "modified": stat.st_mtime,
                    "size": stat.st_size,
                }
            )
    changes.sort(key=lambda x: x["modified"], reverse=True)
    return changes


def find_git_repos(base_path=None):
    """Find git repositories one level deep under base_path."""
    base = Path(base_path) if base_path else Path.home()
    repos = []
    try:
        for item in base.iterdir():
            if item.is_dir() and (item / ".git").exists():
                repos.append(item)
    except PermissionError:
        pass
    return repos


def get_git_commits(repo_path, author_pattern="Claude"):
    """Get git commits matching an author pattern."""
    commits = []
    try:
        result = subprocess.run(
            [
                "git", "-C", str(repo_path), "log",
                f"--author={author_pattern}",
                "--format=%H|%ai|%s", "--all",
            ],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                parts = line.split("|", 2)
                if len(parts) == 3:
                    commits.append(
                        {
                            "hash": parts[0][:8],
                            "full_hash": parts[0],
                            "date": parts[1],
                            "message": parts[2],
                            "repo": str(repo_path),
                        }
                    )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return commits


def get_git_log(repo_path, count=10):
    """Get recent git log entries."""
    entries = []
    try:
        result = subprocess.run(
            [
                "git", "-C", str(repo_path), "log",
                "--format=%H|%ai|%an|%s", f"-{count}",
            ],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                parts = line.split("|", 3)
                if len(parts) == 4:
                    entries.append(
                        {
                            "hash": parts[0][:8],
                            "full_hash": parts[0],
                            "date": parts[1],
                            "author": parts[2],
                            "message": parts[3],
                        }
                    )
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return entries


def get_git_diff_stats(repo_path, commit_hash):
    """Get diff stats for a single commit."""
    try:
        result = subprocess.run(
            [
                "git", "-C", str(repo_path), "diff",
                "--stat", f"{commit_hash}~1", commit_hash,
            ],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip() if result.returncode == 0 else ""
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return ""


def get_git_status(repo_path):
    """Get uncommitted file changes in a repo."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "status", "--short"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            files = []
            for line in result.stdout.strip().split("\n"):
                status = line[:2].strip()
                fname = line[3:]
                files.append({"status": status, "file": fname})
            return files
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return []
