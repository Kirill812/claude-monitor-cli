"""Claude Code Monitor - Live TUI Dashboard."""

import socket
from datetime import datetime
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.reactive import reactive
from textual.widgets import (
    DataTable,
    Footer,
    RichLog,
    Static,
)
from rich.text import Text

from .data import (
    find_git_repos,
    get_active_sessions,
    get_all_sessions_with_status,
    get_file_changes,
    get_git_log,
    get_git_status,
    get_history,
    get_system_stats,
    relative_time,
    sanitize_display,
    ts_to_str,
)


class StatusBar(Static):
    """Top status bar showing server info and resource usage."""

    def compose(self) -> ComposeResult:
        yield Static(id="status-content")

    def update_stats(self, active_count: int, sys_stats: dict) -> None:
        hostname = socket.gethostname()
        now = datetime.now().strftime("%H:%M:%S")
        cpu = sys_stats.get("cpu_percent", 0)
        mem_pct = sys_stats.get("mem_percent", 0)
        mem_used = sys_stats.get("mem_used_gb", 0)
        mem_total = sys_stats.get("mem_total_gb", 0)

        if cpu > 80:
            cpu_style = "bold red"
        elif cpu > 50:
            cpu_style = "bold yellow"
        else:
            cpu_style = "green"

        if mem_pct > 85:
            mem_style = "bold red"
        elif mem_pct > 60:
            mem_style = "yellow"
        else:
            mem_style = "green"

        status = Text()
        status.append(" CLAUDE MONITOR ", style="bold white on rgb(100,50,150)")
        status.append(f"  {hostname}", style="bold cyan")
        status.append(f"  {now}", style="dim")
        status.append("  |  ", style="dim")

        if active_count > 0:
            status.append(f"● {active_count} active", style="bold green")
        else:
            status.append("○ idle", style="dim")

        status.append("  |  ", style="dim")
        status.append("CPU ", style="dim")
        status.append(f"{cpu:.0f}%", style=cpu_style)
        status.append("  MEM ", style="dim")
        status.append(f"{mem_used:.1f}/{mem_total:.1f}GB", style=mem_style)

        self.query_one("#status-content", Static).update(status)


class SessionPanel(Static):
    """Panel showing active Claude Code sessions. Height adapts to content."""

    def compose(self) -> ComposeResult:
        yield Static("[bold]Sessions[/bold]", classes="panel-title")
        yield DataTable(id="session-table")

    def on_mount(self) -> None:
        table = self.query_one("#session-table", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        table.add_columns(
            "Status", "PID", "Directory", "Started", "Procs", "Mem", "CPU"
        )

    def update_sessions(self, sessions: list) -> None:
        table = self.query_one("#session-table", DataTable)
        table.clear()

        for s in sessions:
            is_active = s.get("is_active", False)

            if is_active:
                status = Text("● LIVE", style="bold green")
            else:
                status = Text("○ ended", style="dim")

            pid = str(s.get("pid", "?"))
            cwd = s.get("cwd", "?")
            cwd = cwd.replace(str(Path.home()), "~")
            if len(cwd) > 25:
                cwd = "..." + cwd[-22:]

            started = relative_time(s.get("startedAt", 0))
            children = str(s.get("children", 0)) if is_active else "-"
            mem = f"{s.get('mem_mb', 0):.0f}M" if is_active else "-"
            cpu = f"{s.get('cpu_percent', 0):.0f}%" if is_active else "-"

            table.add_row(status, pid, cwd, started, children, mem, cpu)

        # Adapt height: title(1) + header(1) + border(2) + rows + min 1
        row_count = max(len(sessions), 1)
        # Clamp between 5 and 12
        new_height = min(max(row_count + 4, 5), 12)
        self.styles.height = new_height


class ActivityFeed(Static):
    """Real-time feed of file changes and prompts."""

    def compose(self) -> ComposeResult:
        yield Static("[bold]Activity Feed[/bold]", classes="panel-title")
        yield RichLog(id="activity-log", max_lines=200, markup=True)

    _last_history_len: int = 0
    _last_file_count: int = 0
    _seen_events: set = set()

    def on_mount(self) -> None:
        self._last_history_len = len(get_history())
        self._last_file_count = len(get_file_changes())
        self._seen_events = set()
        log = self.query_one("#activity-log", RichLog)
        log.write(Text("Monitoring started...", style="dim italic"))

        history = get_history()
        for entry in history[-8:]:
            ts = ts_to_str(entry.get("timestamp", 0))
            display = sanitize_display(entry.get("display", ""), max_len=70)
            sid = entry.get("sessionId", "?")[:8]
            line = Text()
            line.append(f" {ts} ", style="dim")
            line.append("PROMPT ", style="bold magenta")
            line.append(f"[{sid}] ", style="dim cyan")
            line.append(display)
            log.write(line)

    def refresh_feed(self) -> None:
        log = self.query_one("#activity-log", RichLog)
        now_str = datetime.now().strftime("%H:%M:%S")

        history = get_history()
        if len(history) > self._last_history_len:
            for entry in history[self._last_history_len:]:
                ts = ts_to_str(entry.get("timestamp", 0))
                display = sanitize_display(entry.get("display", ""), max_len=70)
                sid = entry.get("sessionId", "?")[:8]
                line = Text()
                line.append(f" {ts} ", style="dim")
                line.append("PROMPT ", style="bold magenta")
                line.append(f"[{sid}] ", style="dim cyan")
                line.append(display)
                log.write(line)
            self._last_history_len = len(history)

        files = get_file_changes()
        if len(files) > self._last_file_count:
            new_count = len(files) - self._last_file_count
            for ch in files[:new_count]:
                event_key = f"{ch['file']}@{ch['version']}"
                if event_key not in self._seen_events:
                    self._seen_events.add(event_key)
                    line = Text()
                    line.append(f" {now_str} ", style="dim")
                    line.append("FILE   ", style="bold yellow")
                    line.append(f"[{ch['session_id'][:8]}] ", style="dim cyan")
                    line.append(f"{ch['file']} ", style="white")
                    line.append(f"({ch['version']}, {ch['size']}B)", style="dim")
                    log.write(line)
            self._last_file_count = len(files)


class GitPanel(Static):
    """Panel showing recent git activity across repos."""

    def compose(self) -> ComposeResult:
        yield Static("[bold]Git Activity[/bold]", classes="panel-title")
        yield RichLog(id="git-log", max_lines=100, markup=True)

    def update_git(self) -> None:
        log = self.query_one("#git-log", RichLog)
        log.clear()

        repos = find_git_repos()
        for repo in repos:
            repo_name = repo.name

            status = get_git_status(repo)
            if status:
                header = Text()
                header.append(f" {repo_name}/", style="bold cyan")
                header.append(f"  {len(status)} uncommitted", style="yellow")
                log.write(header)
                for f in status[:5]:
                    s = f["status"]
                    if s in ("A", "??"):
                        style = "green"
                        icon = "+"
                    elif s == "M":
                        style = "yellow"
                        icon = "~"
                    elif s == "D":
                        style = "red"
                        icon = "-"
                    else:
                        style = "white"
                        icon = "?"
                    line = Text()
                    line.append(f"   {icon} ", style=style)
                    line.append(f["file"], style=style)
                    log.write(line)
                if len(status) > 5:
                    log.write(Text(f"   ... +{len(status) - 5} more", style="dim"))
            else:
                header = Text()
                header.append(f" {repo_name}/", style="bold cyan")
                header.append("  clean", style="dim green")
                log.write(header)

            entries = get_git_log(repo, count=5)
            for e in entries:
                is_claude = "claude" in e["author"].lower()
                line = Text()
                if is_claude:
                    line.append("   * ", style="bold cyan")
                else:
                    line.append("     ", style="dim")
                line.append(e["hash"] + " ", style="yellow")
                line.append(
                    e["author"][:12].ljust(12) + " ",
                    style="cyan" if is_claude else "dim",
                )
                msg = e["message"]
                if len(msg) > 50:
                    msg = msg[:47] + "..."
                line.append(msg)
                log.write(line)

            log.write(Text(""))


class PromptHistory(Static):
    """Panel showing recent prompt history."""

    def compose(self) -> ComposeResult:
        yield Static("[bold]Prompt History[/bold]", classes="panel-title")
        yield RichLog(id="prompt-log", max_lines=200, markup=True)

    def update_prompts(self) -> None:
        log = self.query_one("#prompt-log", RichLog)
        log.clear()

        history = get_history()
        by_session = {}
        for entry in history:
            sid = entry.get("sessionId", "unknown")
            by_session.setdefault(sid, []).append(entry)

        for sid, prompts in sorted(
            by_session.items(),
            key=lambda x: x[1][-1].get("timestamp", 0),
            reverse=True,
        ):
            header = Text()
            header.append(f" Session {sid[:12]}...", style="bold cyan")
            header.append(f"  ({len(prompts)} prompts)", style="dim")
            log.write(header)

            for p in prompts[-8:]:
                ts = ts_to_str(p.get("timestamp", 0))
                rel = relative_time(p.get("timestamp", 0))
                display = sanitize_display(p.get("display", ""), max_len=65)
                line = Text()
                line.append(f"   {ts} ", style="dim")
                line.append(f"({rel}) ", style="dim")
                line.append(display)
                log.write(line)

            log.write(Text(""))


CSS = """\
Screen {
    layout: vertical;
}

StatusBar {
    height: 3;
    background: $surface;
    padding: 1 0 0 0;
}

SessionPanel {
    height: auto;
    min-height: 5;
    max-height: 12;
    border: solid $primary;
}

#bottom-panels {
    height: 1fr;
}

ActivityFeed {
    height: 1fr;
    border: solid $secondary;
}

GitPanel {
    height: 1fr;
    border: solid $accent;
}

PromptHistory {
    height: 1fr;
    border: solid $warning;
}

.panel-title {
    dock: top;
    padding: 0 1;
    background: $boost;
    height: 1;
}

#session-table {
    height: auto;
    max-height: 10;
}

#activity-log, #git-log, #prompt-log {
    height: 1fr;
    scrollbar-size: 1 1;
}

DataTable > .datatable--cursor {
    background: $accent 30%;
}
"""


class ClaudeMonitorApp(App):
    """Live monitoring dashboard for Claude Code."""

    TITLE = "Claude Code Monitor"
    CSS = CSS

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("p", "toggle_prompts", "Prompts"),
    ]

    show_prompts = reactive(False)

    def compose(self) -> ComposeResult:
        yield StatusBar()
        yield SessionPanel()
        yield Vertical(
            ActivityFeed(),
            GitPanel(),
            id="bottom-panels",
        )
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_data()
        self.set_interval(2.0, self.refresh_sessions)
        self.set_interval(1.5, self.refresh_activity)
        self.set_interval(5.0, self.refresh_git)
        self.set_interval(2.0, self.refresh_status)

    def refresh_data(self) -> None:
        self.refresh_sessions()
        self.refresh_activity()
        self.refresh_git()
        self.refresh_status()

    def refresh_sessions(self) -> None:
        sessions = get_all_sessions_with_status()
        self.query_one(SessionPanel).update_sessions(sessions)

    def refresh_activity(self) -> None:
        self.query_one(ActivityFeed).refresh_feed()

    def refresh_git(self) -> None:
        try:
            self.query_one(GitPanel).update_git()
        except Exception:
            pass

    def refresh_status(self) -> None:
        active = get_active_sessions()
        stats = get_system_stats()
        self.query_one(StatusBar).update_stats(len(active), stats)

    def action_refresh(self) -> None:
        self.refresh_data()
        self.notify("Refreshed", timeout=1)

    def action_toggle_prompts(self) -> None:
        self.show_prompts = not self.show_prompts
        if self.show_prompts:
            self.notify("Prompt view: use 'p' to toggle back", timeout=2)

    def watch_show_prompts(self, show: bool) -> None:
        container = self.query_one("#bottom-panels", Vertical)
        if show:
            try:
                git = self.query_one(GitPanel)
                git.remove()
            except Exception:
                pass
            prompt_panel = PromptHistory()
            container.mount(prompt_panel)
            prompt_panel.update_prompts()
        else:
            try:
                prompts = self.query_one(PromptHistory)
                prompts.remove()
            except Exception:
                pass
            git_panel = GitPanel()
            container.mount(git_panel)
            git_panel.update_git()


def run():
    app = ClaudeMonitorApp()
    app.run()
