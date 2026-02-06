"""ctx-rm CLI — benchmark and evaluate context eviction strategies for LLM agents."""

from __future__ import annotations

import asyncio
import os
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# ── App setup ────────────────────────────────────────────────────────────────


def _quiet_logs() -> None:
    """Suppress structlog output for non-bench commands."""
    import logging

    logging.basicConfig(level=logging.WARNING)
    import structlog

    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING),
    )


app = typer.Typer(
    name="ctx-rm",
    help="Intelligent context eviction for LLM coding agents.",
    no_args_is_help=True,
    rich_markup_mode="rich",
    pretty_exceptions_enable=False,
)
console = Console()


# ── Enums for validated CLI options ──────────────────────────────────────────


class Driver(StrEnum):
    gemini = "gemini"
    claude = "claude"


class Mode(StrEnum):
    minimal = "minimal"
    ctx_rm = "ctx-rm"
    full = "full"


class Policy(StrEnum):
    lru = "lru"
    clock = "clock"
    budget = "budget"
    arc = "arc"
    innodb = "innodb"


class ScorerChoice(StrEnum):
    heuristic = "heuristic"
    ollama = "ollama"


# ── info ─────────────────────────────────────────────────────────────────────


@app.command()
def info() -> None:
    """Show system status: version, drivers, policies, scorers, and tasks."""
    _quiet_logs()
    from ctx_rm import __version__
    from ctx_rm.config import CtxRmConfig

    config = CtxRmConfig()

    # Driver availability
    async def _check() -> dict[str, bool]:
        from ctx_rm.drivers.claude import ClaudeCodeDriver
        from ctx_rm.drivers.gemini import GeminiCLIDriver

        gemini = await GeminiCLIDriver().check_available()
        claude = await ClaudeCodeDriver().check_available()
        return {"gemini": gemini, "claude": claude}

    drivers = asyncio.run(_check())

    # Task count
    from ctx_rm.benchmarks.loader import TaskLoader

    try:
        loader = TaskLoader(Path("docs/context_removal_benchmark_tasks.yaml"))
        task_count = len(loader.list_task_ids())
    except FileNotFoundError:
        task_count = 0

    # Build output
    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="dim", min_width=18)
    grid.add_column()

    grid.add_row("Version", f"[bold]{__version__}[/bold]")
    grid.add_row("", "")

    # Drivers
    for name, available in drivers.items():
        status = "[green]available[/green]" if available else "[dim]not found[/dim]"
        grid.add_row(f"Driver: {name}", status)

    grid.add_row("", "")

    # Policies
    grid.add_row("Policies", "lru  clock  [bold]budget[/bold]  arc  innodb")

    # Scorer
    scorer_display = f"[bold]{config.scorer}[/bold]"
    if config.scorer == "ollama":
        scorer_display += f"  [dim]({config.ollama_host})[/dim]"
    grid.add_row("Scorer", scorer_display)

    # Embeddings
    grid.add_row("Embeddings", "[green]hashing[/green] [dim](sentence-transformers optional)[/dim]")

    # Store
    grid.add_row("Store", "SQLite + TieredStore [dim](warm/cold/zombie)[/dim]")

    grid.add_row("", "")
    grid.add_row("Tasks loaded", f"{task_count} benchmark scenarios")
    grid.add_row("Token budget", f"{config.token_budget:,}")

    console.print(Panel(grid, title="[bold]ctx-rm[/bold]", border_style="blue", padding=(1, 2)))


# ── tasks ────────────────────────────────────────────────────────────────────


@app.command()
def tasks() -> None:
    """List available benchmark tasks."""
    _quiet_logs()
    from ctx_rm.benchmarks.loader import TaskLoader

    loader = TaskLoader(Path("docs/context_removal_benchmark_tasks.yaml"))
    task_ids = loader.list_task_ids()

    table = Table(
        title="Benchmark Tasks",
        show_lines=False,
        title_style="bold",
        header_style="bold cyan",
        border_style="dim",
    )
    table.add_column("#", style="dim", width=3)
    table.add_column("ID", style="bold")
    table.add_column("Title")
    table.add_column("Pressure", style="yellow")
    table.add_column("Turns", justify="right")
    table.add_column("Needles", justify="right")
    table.add_column("Checks", justify="right")

    for i, tid in enumerate(task_ids, 1):
        task = loader.get_task(tid)
        table.add_row(
            str(i),
            tid,
            task.title.replace("_", " "),
            task.eviction_pressure.replace("_", " "),
            str(task.min_turns),
            str(len(task.needles)),
            str(len(task.evaluation)),
        )

    console.print(table)
    console.print(
        f"\n  [dim]{len(task_ids)} tasks available. Run with:[/dim]"
        "  ctx-rm bench --task CR-001"
    )


# ── bench ────────────────────────────────────────────────────────────────────


@app.command()
def bench(
    task: Annotated[str, typer.Option(
        help="Task ID (e.g. CR-001). Use [bold]ctx-rm tasks[/bold] to list all.",
    )] = "CR-001",
    mode: Annotated[Mode, typer.Option(
        help="Session mode.",
    )] = Mode.ctx_rm,
    driver: Annotated[Driver, typer.Option(
        help="Agent driver.",
    )] = Driver.gemini,
    policy: Annotated[Policy, typer.Option(
        help="Eviction policy (ctx-rm mode only).",
    )] = Policy.budget,
    scorer: Annotated[ScorerChoice, typer.Option(
        help="Scoring strategy.",
    )] = ScorerChoice.heuristic,
    budget: Annotated[int, typer.Option(
        help="Token budget for active context.",
    )] = 100_000,
    output: Annotated[Path, typer.Option(
        help="Output directory for results.",
    )] = Path("./results"),
    all_tasks: Annotated[bool, typer.Option(
        "--all", help="Run all tasks x modes x available drivers.",
    )] = False,
) -> None:
    """Run a benchmark experiment.

    Single run:  ctx-rm bench --task CR-003 --mode ctx-rm --policy arc
    Batch run:   ctx-rm bench --all --policy budget
    """
    from ctx_rm.benchmarks.runner import BenchmarkRunner

    # Apply scorer override to config env before runner reads it
    os.environ["CTX_RM_SCORER"] = scorer.value

    if all_tasks:
        _run_batch(policy=policy, budget=budget, output=output, scorer=scorer)
        return

    # Single run
    console.print()
    header = Text()
    header.append("  bench ", style="bold blue")
    header.append(task, style="bold")
    header.append(f"  {mode.value}", style="cyan")
    header.append(f"  {driver.value}", style="green")
    if mode == Mode.ctx_rm:
        header.append(f"  policy={policy.value}", style="yellow")
        header.append(f"  scorer={scorer.value}", style="magenta")
    header.append(f"  budget={budget:,}", style="dim")
    console.print(header)
    console.print()

    runner = BenchmarkRunner(
        driver_name=driver.value,
        task_id=task,
        mode=mode.value,
        token_budget=budget,
        policy_name=policy.value,
        output_dir=output,
    )
    asyncio.run(runner.run())

    result_dir = output / task / mode.value / driver.value
    if (result_dir / "evaluation.json").exists():
        import orjson

        eval_data = orjson.loads((result_dir / "evaluation.json").read_bytes())
        passed = eval_data.get("all_passed", False)
        status = "[bold green]PASS[/bold green]" if passed else "[bold red]FAIL[/bold red]"
        console.print(f"  Result: {status}  {eval_data.get('summary', '')}")
    console.print(f"  Output: [dim]{result_dir}[/dim]\n")


def _run_batch(
    policy: Policy,
    budget: int,
    output: Path,
    scorer: ScorerChoice,
) -> None:
    """Batch mode: all tasks x 3 modes x available drivers."""
    from ctx_rm.benchmarks.loader import TaskLoader
    from ctx_rm.benchmarks.runner import BenchmarkRunner
    from ctx_rm.drivers.claude import ClaudeCodeDriver
    from ctx_rm.drivers.gemini import GeminiCLIDriver

    loader = TaskLoader(Path("docs/context_removal_benchmark_tasks.yaml"))
    task_ids = loader.list_task_ids()

    # Detect available drivers
    available_drivers: list[str] = []
    for name, cls in [("gemini", GeminiCLIDriver), ("claude", ClaudeCodeDriver)]:
        loop = asyncio.new_event_loop()
        try:
            if loop.run_until_complete(cls().check_available()):
                available_drivers.append(name)
        finally:
            loop.close()

    if not available_drivers:
        console.print(
            "\n  [bold red]No drivers available.[/bold red]"
            "  Install gemini or claude CLI.\n"
        )
        return

    modes = ["minimal", "ctx-rm", "full"]
    total = len(task_ids) * len(modes) * len(available_drivers)

    console.print()
    console.print(
        f"  [bold]Batch:[/bold] {len(task_ids)} tasks x {len(modes)} modes "
        f"x {len(available_drivers)} drivers = [bold]{total}[/bold] runs"
    )
    console.print(f"  [dim]policy={policy.value}  scorer={scorer.value}  budget={budget:,}[/dim]")
    console.print()

    completed = 0
    failed = 0
    for tid in task_ids:
        for m in modes:
            for d in available_drivers:
                completed += 1
                label = f"  [{completed}/{total}]  {tid}  {m}  {d}"
                try:
                    runner = BenchmarkRunner(
                        driver_name=d,
                        task_id=tid,
                        mode=m,
                        token_budget=budget,
                        policy_name=policy.value,
                        output_dir=output,
                    )
                    asyncio.run(runner.run())
                    console.print(f"{label}  [green]done[/green]")
                except Exception as e:
                    failed += 1
                    console.print(f"{label}  [red]error:[/red] {e}")

    console.print()
    status_style = "bold green" if failed == 0 else "bold yellow"
    succeeded = completed - failed
    console.print(
        f"  [{status_style}]Batch complete:[/{status_style}]"
        f" {succeeded}/{total} succeeded"
    )
    if failed:
        console.print(f"  [dim]{failed} runs failed[/dim]")
    console.print()


# ── compare ──────────────────────────────────────────────────────────────────


@app.command()
def compare(
    results_dir: Annotated[Path, typer.Argument(
        help="Directory containing benchmark results.",
    )] = Path("./results"),
) -> None:
    """Compare benchmark results across modes, drivers, and policies.

    Reads nested results/{task}/{mode}/{driver}/ directories and generates
    a summary table with token usage, eviction stats, and pass/fail status.
    """
    _quiet_logs()
    import orjson

    if not results_dir.is_dir():
        console.print(f"\n  [red]Not found:[/red] {results_dir}\n")
        raise typer.Exit(1)

    table = Table(
        title="Benchmark Results",
        show_lines=False,
        title_style="bold",
        header_style="bold cyan",
        border_style="dim",
    )
    table.add_column("Task", style="bold")
    table.add_column("Mode")
    table.add_column("Driver")
    table.add_column("Tokens In", justify="right", style="dim")
    table.add_column("Evicted", justify="right")
    table.add_column("Peak %", justify="right")
    table.add_column("Checks", justify="right")
    table.add_column("Result", justify="center")

    mode_stats: dict[str, dict[str, int]] = {}
    row_count = 0

    for task_dir in sorted(results_dir.iterdir()):
        if not task_dir.is_dir():
            continue
        for mode_dir in sorted(task_dir.iterdir()):
            if not mode_dir.is_dir():
                continue
            for driver_dir in sorted(mode_dir.iterdir()):
                if not driver_dir.is_dir():
                    continue

                metrics_path = driver_dir / "metrics.json"
                eval_path = driver_dir / "evaluation.json"

                if not metrics_path.exists():
                    continue

                metrics_data = orjson.loads(metrics_path.read_bytes())
                s = metrics_data.get("summary", {})

                tokens_in = s.get("total_ingested_tokens", 0)
                tokens_evicted = s.get("total_evicted_tokens", 0)
                peak_util = s.get("peak_utilization", 0)

                checks_str = "--"
                result_str = "[dim]--[/dim]"
                all_passed = None

                if eval_path.exists():
                    eval_data = orjson.loads(eval_path.read_bytes())
                    checks_str = eval_data.get("summary", "--")
                    all_passed = eval_data.get("all_passed", False)
                    if all_passed:
                        result_str = "[bold green]PASS[/bold green]"
                    else:
                        result_str = "[bold red]FAIL[/bold red]"

                # Color eviction column based on mode
                evict_style = ""
                mode_name = mode_dir.name
                if mode_name == "ctx-rm" and tokens_evicted > 0:
                    evict_style = "cyan"

                if evict_style:
                    evict_display = f"[{evict_style}]{tokens_evicted:,}[/{evict_style}]"
                else:
                    evict_display = f"{tokens_evicted:,}"

                # Color peak util
                if peak_util > 0.9:
                    peak_display = f"[red]{peak_util:.0%}[/red]"
                elif peak_util > 0.7:
                    peak_display = f"[yellow]{peak_util:.0%}[/yellow]"
                else:
                    peak_display = f"{peak_util:.0%}"

                table.add_row(
                    task_dir.name,
                    mode_name,
                    driver_dir.name,
                    f"{tokens_in:,}",
                    evict_display,
                    peak_display,
                    checks_str,
                    result_str,
                )
                row_count += 1

                if mode_name not in mode_stats:
                    mode_stats[mode_name] = {"passed": 0, "total": 0}
                mode_stats[mode_name]["total"] += 1
                if all_passed is True:
                    mode_stats[mode_name]["passed"] += 1

    if row_count == 0:
        console.print(f"\n  [dim]No results found in {results_dir}[/dim]\n")
        return

    console.print()
    console.print(table)

    # Mode summary
    if mode_stats:
        console.print()
        summary = Text("  ")
        for mode_name in sorted(mode_stats):
            stats = mode_stats[mode_name]
            pct = (stats["passed"] / stats["total"] * 100) if stats["total"] > 0 else 0
            if pct == 100:
                style = "bold green"
            elif pct > 0:
                style = "yellow"
            else:
                style = "dim"
            summary.append(f"{mode_name}: ", style="bold")
            summary.append(f"{stats['passed']}/{stats['total']} ", style=style)
            summary.append("  ", style="dim")
        console.print(summary)
    console.print()
