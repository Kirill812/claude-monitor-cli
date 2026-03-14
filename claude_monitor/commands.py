"""CLI command implementations."""

import time
from datetime import datetime
from pathlib import Path

from .data import (
    find_git_repos,
    get_active_sessions,
    get_file_changes,
    get_git_commits,
    get_git_diff_stats,
    get_git_log,
    get_git_status,
    get_history,
    get_sessions,
)
from .formatting import c, relative_time, sanitize_display, ts_to_str


def cmd_status(args):
    """Show current Claude Code status overview."""
    print(c("═══ Claude Code Monitor ═══", "bold"))
    print()

    # Active sessions
    active = get_active_sessions()
    if active:
        print(c(f"● {len(active)} active session(s)", "green"))
        for s in active:
            started = ts_to_str(s.get("startedAt", 0))
            rel = relative_time(s.get("startedAt", 0))
            print(
                f"  PID {c(s.get('pid', '?'), 'cyan')} | "
                f"Dir: {c(s.get('cwd', '?'), 'yellow')} | "
                f"Started: {started} ({rel})"
            )
            print(f"  Session: {c(s.get('sessionId', '?')[:16] + '...', 'dim')}")
    else:
        print(c("○ No active sessions", "dim"))
    print()

    # Recent history
    history = get_history()
    if history:
        print(c(f"Recent prompts ({len(history)} total):", "bold"))
        for entry in history[-5:]:
            ts = ts_to_str(entry.get("timestamp", 0))
            rel = relative_time(entry.get("timestamp", 0))
            display = sanitize_display(entry.get("display", ""))
            print(f"  {c(ts, 'dim')} ({rel})  {display}")
    print()

    # File changes
    changes = get_file_changes()
    if changes:
        print(c(f"File history: {len(changes)} file version(s) tracked", "bold"))
        for ch in changes[:5]:
            ts = datetime.fromtimestamp(ch["modified"]).strftime("%Y-%m-%d %H:%M:%S")
            print(
                f"  {c(ts, 'dim')}  {ch['file']} ({ch['version']}, {ch['size']}B)"
            )
    print()


def cmd_sessions(args):
    """List all Claude Code sessions with details."""
    import os

    sessions = get_sessions()
    history = get_history()

    session_prompts = {}
    for entry in history:
        sid = entry.get("sessionId", "")
        session_prompts.setdefault(sid, []).append(entry)

    print(c(f"Sessions ({len(sessions)} total):", "bold"))
    print()

    for sid, info in sorted(
        sessions.items(), key=lambda x: x[1].get("startedAt", 0), reverse=True
    ):
        pid = info.get("pid")
        is_active = pid and os.path.exists(f"/proc/{pid}")
        status = c("● ACTIVE", "green") if is_active else c("○ ended", "dim")

        started = ts_to_str(info.get("startedAt", 0))
        rel = relative_time(info.get("startedAt", 0))

        print(f"  {status}  {c(sid[:16], 'cyan')}...")
        print(
            f"    PID: {pid} | Dir: {info.get('cwd', '?')} | Started: {started} ({rel})"
        )

        prompts = session_prompts.get(sid, [])
        if prompts:
            print(f"    Prompts ({len(prompts)}):")
            for p in prompts[:3]:
                display = sanitize_display(p.get("display", ""), max_len=70)
                print(f"      → {display}")
            if len(prompts) > 3:
                print(f"      ... and {len(prompts) - 3} more")

        fchanges = get_file_changes(sid)
        if fchanges:
            print(f"    Files modified: {len(fchanges)}")
        print()


def cmd_commits(args):
    """Show git commits made by Claude."""
    repos = find_git_repos(args.path)
    if not repos:
        print(c("No git repositories found.", "yellow"))
        return

    all_commits = []
    for repo in repos:
        commits = get_git_commits(repo, args.author)
        all_commits.extend(commits)

    if not all_commits:
        print(c(f"No commits found matching author '{args.author}'.", "yellow"))
        print(c("\nAll recent commits:", "bold"))
        for repo in repos:
            entries = get_git_log(repo)
            if entries:
                print(c(f"\n  {repo.name}/", "cyan"))
                for e in entries:
                    print(
                        f"    {c(e['hash'], 'yellow')} {e['date'][:10]} "
                        f"{c(e['author'], 'magenta')} {e['message']}"
                    )
        return

    print(c(f"Claude commits ({len(all_commits)}):", "bold"))
    print()
    for commit in all_commits:
        print(
            f"  {c(commit['hash'], 'yellow')} {commit['date'][:10]}  "
            f"{c(commit['message'], 'white')}"
        )
        print(f"    Repo: {c(Path(commit['repo']).name, 'cyan')}")

        if args.verbose:
            stats = get_git_diff_stats(commit["repo"], commit["full_hash"])
            if stats:
                for sline in stats.split("\n"):
                    print(f"      {sline}")
        print()


def cmd_diff(args):
    """Show recent changes in git repos."""
    repos = find_git_repos(args.path)
    if not repos:
        print(c("No git repositories found.", "yellow"))
        return

    for repo in repos:
        print(c(f"═══ {repo.name}/ ═══", "bold"))

        # Uncommitted changes
        status_files = get_git_status(repo)
        if status_files:
            print(c("\nUncommitted changes:", "yellow"))
            for f in status_files:
                color = (
                    "green"
                    if f["status"] in ("A", "??")
                    else "yellow" if f["status"] == "M" else "red"
                )
                print(f"  {c(f['status'], color)} {f['file']}")

        # Recent commits
        entries = get_git_log(repo, count=args.count)
        if entries:
            print(c(f"\nLast {args.count} commits:", "bold"))
            for e in entries:
                is_claude = "claude" in e["author"].lower()
                marker = c("*", "cyan") if is_claude else " "
                author_color = "cyan" if is_claude else "dim"
                print(
                    f"  {marker} {c(e['hash'], 'yellow')} "
                    f"{c(e['author'], author_color)} {e['message']}"
                )

                if args.verbose:
                    stats = get_git_diff_stats(repo, e["full_hash"])
                    if stats:
                        for sline in stats.split("\n"):
                            print(f"      {sline}")
        print()


def cmd_watch(args):
    """Watch for changes in real-time."""
    import os

    print(c("Watching for Claude Code changes... (Ctrl+C to stop)", "bold"))
    print()

    last_history_len = len(get_history())
    last_file_count = len(get_file_changes())
    known_sessions = set(s.get("sessionId") for s in get_active_sessions())

    # Track last known commit per repo
    repos = find_git_repos(args.path)
    last_commits = {}
    for repo in repos:
        entries = get_git_log(repo, count=1)
        if entries:
            last_commits[str(repo)] = entries[0]["full_hash"]

    try:
        while True:
            now = ts_to_str(int(time.time() * 1000))

            # Check for new prompts
            history = get_history()
            if len(history) > last_history_len:
                for entry in history[last_history_len:]:
                    ts = ts_to_str(entry.get("timestamp", 0))
                    display = sanitize_display(entry.get("display", ""))
                    print(f"  {c('PROMPT', 'magenta')} {ts}  {display}")
                last_history_len = len(history)

            # Check for new file changes
            files = get_file_changes()
            if len(files) > last_file_count:
                diff = len(files) - last_file_count
                print(
                    f"  {c('FILES', 'yellow')}  {now}  "
                    f"{diff} new file version(s) recorded"
                )
                last_file_count = len(files)

            # Check for new/ended sessions
            current_sessions = set(
                s.get("sessionId") for s in get_active_sessions()
            )
            for sid in current_sessions - known_sessions:
                print(f"  {c('START', 'green')}  {now}  New session: {sid[:16]}...")
            for sid in known_sessions - current_sessions:
                print(f"  {c('END', 'red')}    {now}  Session ended: {sid[:16]}...")
            known_sessions = current_sessions

            # Check for new commits
            repos = find_git_repos(args.path)
            for repo in repos:
                entries = get_git_log(repo, count=1)
                if entries:
                    latest = entries[0]["full_hash"]
                    prev = last_commits.get(str(repo))
                    if prev and latest != prev:
                        print(
                            f"  {c('COMMIT', 'green')} {now}  "
                            f"{c(repo.name, 'cyan')}: "
                            f"{c(entries[0]['hash'], 'yellow')} "
                            f"{entries[0]['message']}"
                        )
                    last_commits[str(repo)] = latest

            time.sleep(args.interval)
    except KeyboardInterrupt:
        print(c("\nStopped.", "dim"))
