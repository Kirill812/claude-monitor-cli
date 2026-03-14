"""CLI entry point and argument parsing."""

import argparse
from pathlib import Path

from . import __version__


def main():
    parser = argparse.ArgumentParser(
        prog="claude-monitor",
        description="Live monitoring dashboard for Claude Code",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
examples:
  claude-monitor                  Launch live dashboard (default)
  claude-monitor --static         One-shot status output
  claude-monitor --static diff    Show recent repo changes
""",
    )
    parser.add_argument(
        "-V", "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.add_argument(
        "--static", action="store_true",
        help="One-shot text output instead of live dashboard",
    )

    sub = parser.add_subparsers(dest="command")

    sub.add_parser("status", aliases=["s"], help="Status overview")
    sub.add_parser("sessions", aliases=["ss"], help="List all sessions")

    p_commits = sub.add_parser("commits", aliases=["c"], help="Git commits by Claude")
    p_commits.add_argument("-a", "--author", default="Claude")
    p_commits.add_argument("-p", "--path", default=str(Path.home()))
    p_commits.add_argument("-v", "--verbose", action="store_true")

    p_diff = sub.add_parser("diff", aliases=["d"], help="Recent repo changes")
    p_diff.add_argument("-p", "--path", default=str(Path.home()))
    p_diff.add_argument("-n", "--count", type=int, default=10)
    p_diff.add_argument("-v", "--verbose", action="store_true")

    args = parser.parse_args()

    # If --static or a subcommand is given, use the old text commands
    if args.static or args.command:
        from .commands import cmd_commits, cmd_diff, cmd_sessions, cmd_status
        commands = {
            "status": cmd_status, "s": cmd_status,
            "sessions": cmd_sessions, "ss": cmd_sessions,
            "commits": cmd_commits, "c": cmd_commits,
            "diff": cmd_diff, "d": cmd_diff,
            None: cmd_status,
        }
        commands[args.command](args)
    else:
        # Launch live TUI dashboard
        from .app import run
        run()
