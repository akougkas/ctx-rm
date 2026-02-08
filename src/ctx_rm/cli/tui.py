"""Live TUI dashboard for ctx-rm bench runs.

Subscribes to ContextBus and AgentLoop event callbacks to render a real-time
Rich Live layout showing agent activity, context window state, eviction log,
and segment map.
"""

from __future__ import annotations

from collections import deque
from typing import Any

from rich.console import Console
from rich.layout import Layout
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


class TuiDashboard:
    """Real-time dashboard driven by ContextBus + AgentLoop events."""

    def __init__(self, task_id: str = "", mode: str = "ctx-rm", budget: int = 0) -> None:
        self.task_id = task_id
        self.mode = mode
        self.budget = budget

        # State
        self._turn: int = 0
        self._max_turns: int = 30
        self._active_tokens: int = 0
        self._active_segments: int = 0
        self._warm_count: int = 0
        self._cold_count: int = 0
        self._total_evictions: int = 0
        self._total_recalls: int = 0
        self._total_prompt_tokens: int = 0
        self._total_completion_tokens: int = 0

        # Rolling logs (bounded)
        self._tool_log: deque[str] = deque(maxlen=8)
        self._eviction_log: deque[str] = deque(maxlen=8)
        self._segment_map: deque[tuple[str, str, str]] = deque(maxlen=12)
        # (seg_id_short, source, state: "active"|"evicted"|"recalled"|"pinned")

        self._live: Live | None = None
        self._console = Console()

    def set_max_turns(self, max_turns: int) -> None:
        self._max_turns = max_turns

    # ── Event handlers ────────────────────────────────────────────────

    def on_bus_event(self, event: str, data: dict[str, Any]) -> None:
        """Handle ContextBus events."""
        if event == "ingest":
            self._active_tokens = data.get("active_tokens", self._active_tokens)
            source = data.get("source", "?")
            seg_short = data.get("seg_id", "")[:8]
            if data.get("bypassed"):
                self._warm_count += 1
                self._segment_map.append((seg_short, source or "?", "warm"))
            else:
                self._active_segments += 1
                pinned = "pinned" if "system" in (source or "") else "active"
                self._segment_map.append((seg_short, source or "?", pinned))

        elif event == "evict":
            self._active_tokens = data.get("active_tokens", self._active_tokens)
            self._total_evictions += 1
            self._active_segments = max(0, self._active_segments - 1)
            self._warm_count += 1
            source = data.get("source", "?")
            tokens = data.get("tokens", 0)
            score = data.get("score")
            score_str = f", score {score:.2f}" if score is not None else ""
            self._eviction_log.append(
                f"[T{self._turn}] {source}  -{tokens} tok{score_str}"
            )
            # Update segment map state
            seg_id = data.get("seg_id", "")[:8]
            for i, (sid, src, _) in enumerate(self._segment_map):
                if sid == seg_id:
                    self._segment_map[i] = (sid, src, "evicted")
                    break

        elif event == "recall":
            self._active_tokens = data.get("active_tokens", self._active_tokens)
            self._total_recalls += 1
            self._active_segments += 1
            seg_id = data.get("seg_id", "")[:8]
            for i, (sid, src, _) in enumerate(self._segment_map):
                if sid == seg_id:
                    self._segment_map[i] = (sid, src, "recalled")
                    break

        elif event == "turn_advance":
            self._turn = data.get("turn_number", self._turn)
            self._active_tokens = data.get("active_tokens", self._active_tokens)

        self._refresh()

    def on_loop_event(self, event: str, data: dict[str, Any]) -> None:
        """Handle AgentLoop events."""
        if event == "turn_start":
            self._active_segments = data.get("active_segments", self._active_segments)
            self._active_tokens = data.get("active_tokens", self._active_tokens)

        elif event == "turn_end":
            self._total_prompt_tokens += data.get("prompt_tokens", 0)
            self._total_completion_tokens += data.get("completion_tokens", 0)

        elif event == "tool_call":
            name = data.get("name", "?")
            preview = data.get("args_preview", "")[:60]
            self._tool_log.append(f"> {name} {preview}")

        elif event == "recall_attempt":
            found = data.get("found_count", 0)
            if found > 0:
                self._tool_log.append(f"  recall: {found} candidates found")

        self._refresh()

    # ── Live context manager ──────────────────────────────────────────

    def start(self) -> None:
        """Start the Live display."""
        self._live = Live(
            self._build_layout(),
            console=self._console,
            refresh_per_second=4,
            transient=True,
        )
        self._live.start()

    def stop(self) -> None:
        """Stop the Live display."""
        if self._live is not None:
            self._live.stop()
            self._live = None

    def _refresh(self) -> None:
        if self._live is not None:
            self._live.update(self._build_layout())

    # ── Layout construction ───────────────────────────────────────────

    def _build_layout(self) -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body"),
        )
        layout["body"].split_row(
            Layout(name="left"),
            Layout(name="right"),
        )
        layout["left"].split_column(
            Layout(name="activity"),
            Layout(name="evictions"),
        )
        layout["right"].split_column(
            Layout(name="context"),
            Layout(name="segments"),
        )

        layout["header"].update(self._header_panel())
        layout["activity"].update(self._activity_panel())
        layout["evictions"].update(self._eviction_panel())
        layout["context"].update(self._context_panel())
        layout["segments"].update(self._segment_panel())

        return layout

    def _header_panel(self) -> Panel:
        header = Text()
        header.append("  ctx-rm Live Dashboard", style="bold blue")
        header.append(f"    Task: {self.task_id}", style="bold")
        header.append(f"  Mode: {self.mode}", style="cyan")
        return Panel(header, style="dim")

    def _activity_panel(self) -> Panel:
        lines = Text()
        lines.append(f"Turn {self._turn}/{self._max_turns}\n", style="bold")
        lines.append(f"Prompt tokens: {self._total_prompt_tokens:,}\n", style="dim")
        lines.append(f"Completion tokens: {self._total_completion_tokens:,}\n", style="dim")
        lines.append("\n")
        for entry in self._tool_log:
            lines.append(f"{entry}\n", style="green")
        return Panel(lines, title="Agent Activity", border_style="green")

    def _eviction_panel(self) -> Panel:
        lines = Text()
        for entry in self._eviction_log:
            lines.append(f"{entry}\n", style="yellow")
        if not self._eviction_log:
            lines.append("(none yet)\n", style="dim")
        lines.append(f"\nRecalls: {self._total_recalls}", style="cyan")
        return Panel(lines, title="Eviction Log", border_style="yellow")

    def _context_panel(self) -> Panel:
        lines = Text()
        utilization = (
            self._active_tokens / self.budget if self.budget > 0 else 0
        )
        pct = int(utilization * 100)
        bar_filled = int(utilization * 10)
        bar_empty = 10 - bar_filled
        bar_color = "green" if pct < 70 else ("yellow" if pct < 90 else "red")

        bar_str = "\u2588" * bar_filled + "\u2591" * bar_empty
        lines.append(f"{bar_str}", style=bar_color)
        lines.append(f"  {pct}% ({self._active_tokens:,})\n")
        lines.append(f"Budget: {self.budget:,} tokens\n", style="dim")
        lines.append(f"Active: {self._active_segments} segments\n")
        lines.append(f"Warm: {self._warm_count}", style="yellow")
        lines.append(f"  Cold: {self._cold_count}\n", style="blue")
        lines.append(f"Evictions: {self._total_evictions}", style="red")
        return Panel(lines, title="Context Window", border_style="blue")

    def _segment_panel(self) -> Panel:
        lines = Text()
        state_styles = {
            "active": ("green", "\u25a0"),
            "pinned": ("bold green", "\u25a0"),
            "evicted": ("red", "\u25a1"),
            "recalled": ("cyan", "\u25a0"),
            "warm": ("yellow", "\u25a1"),
        }
        for seg_id, source, state in self._segment_map:
            style, icon = state_styles.get(state, ("dim", "?"))
            label = source if len(source) <= 24 else source[:24]
            suffix = ""
            if state == "evicted":
                suffix = " (ev)"
            elif state == "recalled":
                suffix = " (rc)"
            elif state == "pinned":
                suffix = " (pin)"
            lines.append(f" {icon} {label}{suffix}\n", style=style)
        if not self._segment_map:
            lines.append("(no segments yet)\n", style="dim")
        return Panel(lines, title="Segment Map", border_style="magenta")


def print_post_run_summary(
    console: Console,
    task_id: str,
    mode: str,
    passed: bool | None,
    checks_summary: str,
    prompt_tokens: int,
    completion_tokens: int,
    turns: int,
    evictions: int,
    recalls: int,
    active_tokens: int,
    budget: int,
    utilization_history: list[float] | None = None,
) -> None:
    """Print a Rich post-run summary panel."""
    # Status
    if passed is None:
        status_text = Text("UNKNOWN", style="dim")
    elif passed:
        status_text = Text("PASS", style="bold green")
    else:
        status_text = Text("FAIL", style="bold red")

    table = Table.grid(padding=(0, 2))
    table.add_column(style="dim", min_width=20)
    table.add_column()

    table.add_row("Result", status_text)
    table.add_row("Checks", checks_summary)
    table.add_row("", "")
    table.add_row("Turns", str(turns))
    table.add_row("Prompt tokens", f"{prompt_tokens:,}")
    table.add_row("Completion tokens", f"{completion_tokens:,}")
    table.add_row("", "")
    table.add_row("Evictions", str(evictions))
    table.add_row("Recalls", str(recalls))

    utilization = active_tokens / budget * 100 if budget > 0 else 0
    table.add_row("Final utilization", f"{utilization:.0f}% ({active_tokens:,}/{budget:,})")

    # ASCII sparkline of utilization history
    if utilization_history and len(utilization_history) > 1:
        sparkline = _sparkline(utilization_history)
        table.add_row("Utilization curve", sparkline)

    title = f"[bold]{task_id}[/bold]  {mode}"
    console.print()
    console.print(Panel(table, title=title, border_style="blue", padding=(1, 2)))
    console.print()


def _sparkline(values: list[float], width: int = 20) -> str:
    """Render a simple ASCII sparkline."""
    if not values:
        return ""
    blocks = " \u2581\u2582\u2583\u2584\u2585\u2586\u2587\u2588"
    mn, mx = min(values), max(values)
    spread = mx - mn if mx != mn else 1.0

    # Resample to width
    step = max(1, len(values) // width)
    sampled = [values[i] for i in range(0, len(values), step)][:width]

    chars = []
    for v in sampled:
        idx = int((v - mn) / spread * (len(blocks) - 1))
        chars.append(blocks[idx])
    return "".join(chars)
