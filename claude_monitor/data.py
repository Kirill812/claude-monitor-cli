"""Data access layer for Claude Code artifacts."""

import asyncio
import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import psutil

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
    """Get sessions whose PID is still running, enriched with process info."""
    sessions = get_sessions()
    active = []
    for sid, info in sessions.items():
        pid = info.get("pid")
        if pid and os.path.exists(f"/proc/{pid}"):
            # Enrich with process stats
            try:
                proc = psutil.Process(pid)
                info["cpu_percent"] = proc.cpu_percent(interval=0)
                mem = proc.memory_info()
                info["mem_mb"] = mem.rss / (1024 * 1024)
                info["status"] = proc.status()
                # Count child processes (subagents, tools)
                children = proc.children(recursive=True)
                info["children"] = len(children)
                info["total_mem_mb"] = info["mem_mb"] + sum(
                    c.memory_info().rss / (1024 * 1024) for c in children
                    if c.is_running()
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                info["cpu_percent"] = 0
                info["mem_mb"] = 0
                info["status"] = "unknown"
                info["children"] = 0
                info["total_mem_mb"] = 0
            active.append(info)
    return active


def get_all_sessions_with_status():
    """Get all sessions marked as active or ended."""
    sessions = get_sessions()
    result = []
    for sid, info in sessions.items():
        pid = info.get("pid")
        info["is_active"] = bool(pid and os.path.exists(f"/proc/{pid}"))
        if info["is_active"]:
            try:
                proc = psutil.Process(pid)
                info["cpu_percent"] = proc.cpu_percent(interval=0)
                mem = proc.memory_info()
                info["mem_mb"] = mem.rss / (1024 * 1024)
                children = proc.children(recursive=True)
                info["children"] = len(children)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                info["cpu_percent"] = 0
                info["mem_mb"] = 0
                info["children"] = 0
        result.append(info)
    result.sort(key=lambda x: (not x["is_active"], -x.get("startedAt", 0)))
    return result


def get_history():
    """Parse the prompt history JSONL file."""
    entries = []
    if not HISTORY_FILE.exists():
        return entries
    try:
        text = HISTORY_FILE.read_text().strip()
    except OSError:
        return entries
    for line in text.split("\n"):
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
            try:
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
            except OSError:
                pass
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


async def async_git_command(*args, timeout=10):
    """Run a git command asynchronously."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        if proc.returncode == 0:
            return stdout.decode().strip()
    except (asyncio.TimeoutError, FileNotFoundError, OSError):
        pass
    return ""


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


def get_system_stats():
    """Get system resource usage."""
    cpu = psutil.cpu_percent(interval=0)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    return {
        "cpu_percent": cpu,
        "mem_total_gb": mem.total / (1024 ** 3),
        "mem_used_gb": mem.used / (1024 ** 3),
        "mem_percent": mem.percent,
        "disk_total_gb": disk.total / (1024 ** 3),
        "disk_used_gb": disk.used / (1024 ** 3),
        "disk_percent": disk.percent,
    }


def sanitize_display(text, max_len=80):
    """Truncate and redact sensitive content from display text."""
    if "eyJ" in text or "token" in text.lower():
        return "[redacted]"
    if len(text) > max_len:
        return text[: max_len - 3] + "..."
    return text


def relative_time(ts_ms):
    """Convert millisecond timestamp to relative time string."""
    now = datetime.now().timestamp() * 1000
    diff_s = (now - ts_ms) / 1000
    if diff_s < 0:
        return "just now"
    if diff_s < 60:
        return f"{int(diff_s)}s ago"
    elif diff_s < 3600:
        return f"{int(diff_s / 60)}m ago"
    elif diff_s < 86400:
        h = int(diff_s / 3600)
        m = int((diff_s % 3600) / 60)
        return f"{h}h{m}m ago"
    else:
        return f"{int(diff_s / 86400)}d ago"


def ts_to_str(ts_ms):
    """Convert millisecond timestamp to readable string."""
    dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).astimezone()
    return dt.strftime("%H:%M:%S")
