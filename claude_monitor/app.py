"""Claude Code Monitor - Live TUI Dashboard."""

import socket
from datetime import datetime
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
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

    def update_stats(self, active_count: int, sys_stats: dict, selected_sid: str = "") -> None:
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

        if selected_sid:
            status.append("  |  ", style="dim")
            status.append(f"Monitoring: {selected_sid[:12]}...", style="bold yellow")

        self.query_one("#status-content", Static).update(status)


class SessionPanel(Static):
    """Panel showing Claude Code sessions. Select one with Enter."""

    class Selected(Message):
        """Emitted when a session is selected."""
        def __init__(self, session_id: str) -> None:
            self.session_id = session_id
            super().__init__()

    class Deselected(Message):
        """Emitted when selection is cleared."""

    # Store session list for row->session mapping
    _sessions: list = []

    def compose(self) -> ComposeResult:
        yield Static("[bold]Sessions[/bold]  [dim]Enter=select  Esc=all[/dim]", classes="panel-title")
        yield DataTable(id="session-table")

    def on_mount(self) -> None:
        table = self.query_one("#session-table", DataTable)
        table.cursor_type = "row"
        table.zebra_stripes = True
        table.add_columns(
            "Status", "PID", "Session ID", "Directory", "Started", "Procs", "Mem", "CPU"
        )

    def update_sessions(self, sessions: list, selected_sid: str = "") -> None:
        table = self.query_one("#session-table", DataTable)
        table.clear()
        self._sessions = sessions

        for s in sessions:
            is_active = s.get("is_active", False)
            sid = s.get("sessionId", "?")
            is_selected = sid == selected_sid

            if is_selected:
                status = Text("▶ WATCH", style="bold yellow")
            elif is_active:
                status = Text("● LIVE", style="bold green")
            else:
                status = Text("○ ended", style="dim")

            pid = str(s.get("pid", "?"))
            sid_short = sid[:12] + "..."
            cwd = s.get("cwd", "?")
            cwd = cwd.replace(str(Path.home()), "~")
            if len(cwd) > 20:
                cwd = "..." + cwd[-17:]

            started = relative_time(s.get("startedAt", 0))
            children = str(s.get("children", 0)) if is_active else "-"
            mem = f"{s.get('mem_mb', 0):.0f}M" if is_active else "-"
            cpu = f"{s.get('cpu_percent', 0):.0f}%" if is_active else "-"

            table.add_row(status, pid, sid_short, cwd, started, children, mem, cpu)

        row_count = max(len(sessions), 1)
        new_height = min(max(row_count + 4, 5), 12)
        self.styles.height = new_height

    def on_data_table_row_selected(self, event: DataTable.RowSelected) -> None:
        row_idx = event.cursor_row
        if 0 <= row_idx < len(self._sessions):
            sid = self._sessions[row_idx].get("sessionId", "")
            self.post_message(self.Selected(sid))

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.post_message(self.Deselected())


class ActivityFeed(Static):
    """Real-time feed of file changes and prompts."""

    def compose(self) -> ComposeResult:
        yield Static(id="activity-title", classes="panel-title")
        yield RichLog(id="activity-log", max_lines=500, markup=True)

    _last_history_len: int = 0
    _last_file_count: int = 0
    _seen_events: set = set()
    _filter_sid: str = ""

    def on_mount(self) -> None:
        self._last_history_len = 0
        self._last_file_count = 0
        self._seen_events = set()
        self._filter_sid = ""
        self._update_title()
        self._load_initial()

    def _update_title(self) -> None:
        title = self.query_one("#activity-title", Static)
        if self._filter_sid:
            title.update(
                f"[bold]Activity Feed[/bold]  [dim]session {self._filter_sid[:12]}...[/dim]"
            )
        else:
            title.update("[bold]Activity Feed[/bold]  [dim]all sessions[/dim]")

    def set_filter(self, session_id: str) -> None:
        """Set or clear session filter. Reloads the feed."""
        self._filter_sid = session_id
        self._seen_events = set()
        self._update_title()
        log = self.query_one("#activity-log", RichLog)
        log.clear()
        self._load_initial()

    def _load_initial(self) -> None:
        log = self.query_one("#activity-log", RichLog)

        if self._filter_sid:
            log.write(Text(f"Monitoring session {self._filter_sid[:12]}...", style="dim italic"))
        else:
            log.write(Text("Monitoring all sessions...", style="dim italic"))

        # Load recent prompts
        history = get_history()
        if self._filter_sid:
            history = [h for h in history if h.get("sessionId", "") == self._filter_sid]
        self._last_history_len = len(get_history())  # track global count

        for entry in history[-10:]:
            self._write_prompt(log, entry)

        # Load recent file changes
        changes = get_file_changes(self._filter_sid if self._filter_sid else None)
        self._last_file_count = len(get_file_changes())  # track global count

        for ch in changes[:5]:
            event_key = f"{ch['file']}@{ch['version']}"
            self._seen_events.add(event_key)
            self._write_file_change(log, ch)

    def _write_prompt(self, log: RichLog, entry: dict) -> None:
        ts = ts_to_str(entry.get("timestamp", 0))
        display = sanitize_display(entry.get("display", ""), max_len=70)
        sid = entry.get("sessionId", "?")[:8]
        line = Text()
        line.append(f" {ts} ", style="dim")
        line.append("PROMPT ", style="bold magenta")
        if not self._filter_sid:
            line.append(f"[{sid}] ", style="dim cyan")
        line.append(display)
        log.write(line)

    def _write_file_change(self, log: RichLog, ch: dict) -> None:
        ts = datetime.fromtimestamp(ch["modified"]).strftime("%H:%M:%S")
        line = Text()
        line.append(f" {ts} ", style="dim")
        line.append("FILE   ", style="bold yellow")
        if not self._filter_sid:
            line.append(f"[{ch['session_id'][:8]}] ", style="dim cyan")
        line.append(f"{ch['file']} ", style="white")
        line.append(f"({ch['version']}, {ch['size']}B)", style="dim")
        log.write(line)

    def refresh_feed(self) -> None:
        log = self.query_one("#activity-log", RichLog)

        # New prompts
        all_history = get_history()
        if len(all_history) > self._last_history_len:
            new_entries = all_history[self._last_history_len:]
            if self._filter_sid:
                new_entries = [
                    h for h in new_entries
                    if h.get("sessionId", "") == self._filter_sid
                ]
            for entry in new_entries:
                self._write_prompt(log, entry)
            self._last_history_len = len(all_history)

        # New file changes
        all_files = get_file_changes()
        if len(all_files) > self._last_file_count:
            new_count = len(all_files) - self._last_file_count
            new_files = all_files[:new_count]
            if self._filter_sid:
                new_files = [
                    f for f in new_files
                    if f.get("session_id", "") == self._filter_sid
                ]
            for ch in new_files:
                event_key = f"{ch['file']}@{ch['version']}"
                if event_key not in self._seen_events:
                    self._seen_events.add(event_key)
                    self._write_file_change(log, ch)
            self._last_file_count = len(all_files)


class GitPanel(Static):
    """Panel showing recent git activity across repos."""

    _filter_cwd: str = ""

    def compose(self) -> ComposeResult:
        yield Static(id="git-title", classes="panel-title")
        yield RichLog(id="git-log", max_lines=100, markup=True)

    def on_mount(self) -> None:
        self._update_title()

    def _update_title(self) -> None:
        title = self.query_one("#git-title", Static)
        if self._filter_cwd:
            name = Path(self._filter_cwd).name
            title.update(f"[bold]Git Activity[/bold]  [dim]{name}/[/dim]")
        else:
            title.update("[bold]Git Activity[/bold]  [dim]all repos[/dim]")

    def set_filter(self, cwd: str) -> None:
        self._filter_cwd = cwd
        self._update_title()
        self.update_git()

    def update_git(self) -> None:
        log = self.query_one("#git-log", RichLog)
        log.clear()

        repos = find_git_repos()

        # If filtering by cwd, only show repos under that directory
        if self._filter_cwd:
            cwd_path = Path(self._filter_cwd)
            repos = [r for r in repos if r == cwd_path or cwd_path in r.parents or r in cwd_path.parents]
            # Also check if cwd itself is a git repo
            if cwd_path.is_dir() and (cwd_path / ".git").exists() and cwd_path not in repos:
                repos.append(cwd_path)

        if not repos:
            log.write(Text(" No git repos found", style="dim"))
            return

        for repo in repos:
            repo_name = repo.name

            status = get_git_status(repo)
            if status:
                header = Text()
                header.append(f" {repo_name}/", style="bold cyan")
                header.append(f"  {len(status)} uncommitted", style="yellow")
                log.write(header)
                for f in status[:8]:
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
                if len(status) > 8:
                    log.write(Text(f"   ... +{len(status) - 8} more", style="dim"))
            else:
                header = Text()
                header.append(f" {repo_name}/", style="bold cyan")
                header.append("  clean", style="dim green")
                log.write(header)

            entries = get_git_log(repo, count=8)
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
    """Panel showing prompt history for selected or all sessions."""

    _filter_sid: str = ""

    def compose(self) -> ComposeResult:
        yield Static(id="prompt-title", classes="panel-title")
        yield RichLog(id="prompt-log", max_lines=500, markup=True)

    def on_mount(self) -> None:
        self._update_title()

    def _update_title(self) -> None:
        title = self.query_one("#prompt-title", Static)
        if self._filter_sid:
            title.update(
                f"[bold]Prompt History[/bold]  [dim]session {self._filter_sid[:12]}...[/dim]"
            )
        else:
            title.update("[bold]Prompt History[/bold]  [dim]all sessions[/dim]")

    def set_filter(self, session_id: str) -> None:
        self._filter_sid = session_id
        self._update_title()
        self.update_prompts()

    def update_prompts(self) -> None:
        log = self.query_one("#prompt-log", RichLog)
        log.clear()

        history = get_history()

        if self._filter_sid:
            # Show all prompts for this session
            prompts = [
                h for h in history
                if h.get("sessionId", "") == self._filter_sid
            ]
            if not prompts:
                log.write(Text(" No prompts for this session", style="dim"))
                return

            for p in prompts:
                ts = ts_to_str(p.get("timestamp", 0))
                rel = relative_time(p.get("timestamp", 0))
                display = sanitize_display(p.get("display", ""), max_len=70)
                line = Text()
                line.append(f" {ts} ", style="dim")
                line.append(f"({rel}) ", style="dim")
                line.append(display)
                log.write(line)
        else:
            # Group by session
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
        Binding("escape", "deselect", "All Sessions", show=True),
    ]

    show_prompts = reactive(False)
    selected_session_id = reactive("")
    _selected_cwd: str = ""

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
        self.query_one(SessionPanel).update_sessions(sessions, self.selected_session_id)
        # Update stored cwd for git filtering
        if self.selected_session_id:
            for s in sessions:
                if s.get("sessionId") == self.selected_session_id:
                    self._selected_cwd = s.get("cwd", "")
                    break

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
        self.query_one(StatusBar).update_stats(
            len(active), stats, self.selected_session_id
        )

    def action_refresh(self) -> None:
        self.refresh_data()
        self.notify("Refreshed", timeout=1)

    def action_deselect(self) -> None:
        if self.selected_session_id:
            self.selected_session_id = ""
            self._selected_cwd = ""
            self._apply_filter()
            self.notify("Showing all sessions", timeout=1)

    def on_session_panel_selected(self, message: SessionPanel.Selected) -> None:
        self.selected_session_id = message.session_id
        # Find the cwd for this session
        sessions = get_all_sessions_with_status()
        for s in sessions:
            if s.get("sessionId") == message.session_id:
                self._selected_cwd = s.get("cwd", "")
                break
        self._apply_filter()
        self.notify(f"Monitoring session {message.session_id[:12]}...", timeout=2)

    def on_session_panel_deselected(self, message: SessionPanel.Deselected) -> None:
        self.action_deselect()

    def _apply_filter(self) -> None:
        """Apply session filter to all panels."""
        sid = self.selected_session_id
        self.query_one(ActivityFeed).set_filter(sid)
        try:
            self.query_one(GitPanel).set_filter(self._selected_cwd if sid else "")
        except Exception:
            pass
        try:
            self.query_one(PromptHistory).set_filter(sid)
        except Exception:
            pass
        self.refresh_sessions()
        self.refresh_status()

    def action_toggle_prompts(self) -> None:
        self.show_prompts = not self.show_prompts

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
            prompt_panel.set_filter(self.selected_session_id)
        else:
            try:
                prompts = self.query_one(PromptHistory)
                prompts.remove()
            except Exception:
                pass
            git_panel = GitPanel()
            container.mount(git_panel)
            git_panel.set_filter(self._selected_cwd if self.selected_session_id else "")


def run():
    app = ClaudeMonitorApp()
    app.run()
