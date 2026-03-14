"""CLI entry point and argument parsing."""

import argparse
from pathlib import Path

from . import __version__
from .commands import cmd_commits, cmd_diff, cmd_sessions, cmd_status, cmd_watch


def main():
    parser = argparse.ArgumentParser(
        prog="claude-monitor",
        description="Monitor changes made by Claude Code on this server",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  claude-monitor                  Status overview (default)
  claude-monitor sessions         List all sessions
  claude-monitor commits          Git commits by Claude
  claude-monitor diff             Recent repo changes
  claude-monitor diff -v          With file-level stats
  claude-monitor watch            Real-time monitoring
  claude-monitor watch -i 5       Poll every 5 seconds
""",
    )
    parser.add_argument(
        "-V", "--version", action="version", version=f"%(prog)s {__version__}"
    )

    sub = parser.add_subparsers(dest="command")

    # status
    sub.add_parser("status", aliases=["s"], help="Status overview")

    # sessions
    sub.add_parser("sessions", aliases=["ss"], help="List all sessions")

    # commits
    p_commits = sub.add_parser("commits", aliases=["c"], help="Git commits by Claude")
    p_commits.add_argument(
        "-a", "--author", default="Claude", help="Author pattern (default: Claude)"
    )
    p_commits.add_argument(
        "-p", "--path", default=str(Path.home()), help="Base path to scan for repos"
    )
    p_commits.add_argument(
        "-v", "--verbose", action="store_true", help="Show file-level diff stats"
    )

    # diff
    p_diff = sub.add_parser("diff", aliases=["d"], help="Recent repo changes")
    p_diff.add_argument(
        "-p", "--path", default=str(Path.home()), help="Base path to scan for repos"
    )
    p_diff.add_argument(
        "-n", "--count", type=int, default=10, help="Number of commits (default: 10)"
    )
    p_diff.add_argument(
        "-v", "--verbose", action="store_true", help="Show file-level diff stats"
    )

    # watch
    p_watch = sub.add_parser("watch", aliases=["w"], help="Real-time monitoring")
    p_watch.add_argument(
        "-i", "--interval", type=int, default=3, help="Poll interval in seconds (default: 3)"
    )
    p_watch.add_argument(
        "-p", "--path", default=str(Path.home()), help="Base path to scan for repos"
    )

    args = parser.parse_args()

    commands = {
        "status": cmd_status, "s": cmd_status,
        "sessions": cmd_sessions, "ss": cmd_sessions,
        "commits": cmd_commits, "c": cmd_commits,
        "diff": cmd_diff, "d": cmd_diff,
        "watch": cmd_watch, "w": cmd_watch,
        None: cmd_status,
    }

    commands[args.command](args)
