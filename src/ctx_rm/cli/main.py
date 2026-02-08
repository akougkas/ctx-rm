"""ctx-rm CLI — benchmark and evaluate context eviction strategies for LLM agents."""

from __future__ import annotations

import asyncio
import os
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any

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
    sequential = "sequential"


class BatchMode(StrEnum):
    fixed = "fixed"
    adaptive = "adaptive"


# ── info ─────────────────────────────────────────────────────────────────────


@app.command()
def info() -> None:
    """Show system status: version, policies, scorers, and tasks."""
    _quiet_logs()
    from ctx_rm import __version__
    from ctx_rm.config import CtxRmConfig

    config = CtxRmConfig()

    # Driver availability
    async def _check() -> dict[str, bool]:
        from ctx_rm.drivers.llamacpp import LlamaCppDriver

        try:
            llamacpp = await LlamaCppDriver(base_url=config.llama_base_url).check_available()
        except Exception:
            llamacpp = False
        return {"llamacpp": llamacpp}

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
    policy: Annotated[Policy, typer.Option(
        help="Eviction policy (ctx-rm mode only).",
    )] = Policy.budget,
    scorer: Annotated[ScorerChoice, typer.Option(
        help="Scoring strategy.",
    )] = ScorerChoice.heuristic,
    batch_mode: Annotated[BatchMode, typer.Option(
        help="Eviction batch mode (ctx-rm mode only).",
    )] = BatchMode.fixed,
    budget: Annotated[int, typer.Option(
        help="Token budget for active context.",
    )] = 100_000,
    output: Annotated[Path, typer.Option(
        help="Output directory for results.",
    )] = Path("./results"),
    run_index: Annotated[int, typer.Option(
        help="Run repetition index (1, 2, 3...).",
    )] = 1,
    enable_recall: Annotated[bool, typer.Option(
        help="Enable recall (page-fault semantics).",
    )] = False,
    max_turns: Annotated[int, typer.Option(
        help="Maximum agent turns.",
    )] = 30,
    all_tasks: Annotated[bool, typer.Option(
        "--all", help="Run all tasks x modes.",
    )] = False,
    live: Annotated[bool, typer.Option(
        "--live", help="Show live TUI dashboard during run.",
    )] = False,
) -> None:
    """Run a benchmark experiment.

    Single run:  ctx-rm bench --task CR-003 --mode ctx-rm --policy arc
    Batch run:   ctx-rm bench --all --policy budget
    """
    os.environ["CTX_RM_SCORER"] = scorer.value
    os.environ["CTX_RM_EVICTION_BATCH_MODE"] = batch_mode.value

    if all_tasks:
        _run_batch(
            policy=policy,
            budget=budget,
            output=output,
            scorer=scorer,
            batch_mode=batch_mode,
            enable_recall=enable_recall,
            max_turns=max_turns,
        )
        return

    console.print()
    header = Text()
    header.append("  bench ", style="bold blue")
    header.append(task, style="bold")
    header.append(f"  {mode.value}", style="cyan")
    header.append("  llamacpp", style="green")
    if mode == Mode.ctx_rm:
        header.append(f"  policy={policy.value}", style="yellow")
        header.append(f"  scorer={scorer.value}", style="magenta")
        header.append(f"  batch={batch_mode.value}", style="magenta")
        header.append(f"  recall={enable_recall}", style="magenta")
    header.append(f"  budget={budget:,}", style="dim")
    header.append(f"  run={run_index}", style="dim")
    console.print(header)
    console.print()

    from ctx_rm.benchmarks.runner import BenchmarkRunner

    # Set up live TUI if requested
    tui = None
    if live:
        from ctx_rm.cli.tui import TuiDashboard

        tui = TuiDashboard(task_id=task, mode=mode.value, budget=budget)
        tui.set_max_turns(max_turns)
        tui.start()

    try:
        runner = BenchmarkRunner(
            driver_name="llamacpp",
            task_id=task,
            mode=mode.value,
            token_budget=budget,
            policy_name=policy.value,
            output_dir=output,
            run_index=run_index,
            max_turns=max_turns,
            enable_recall=enable_recall,
            on_bus_event=tui.on_bus_event if tui else None,
            on_loop_event=tui.on_loop_event if tui else None,
        )
        asyncio.run(runner.run())
    finally:
        if tui is not None:
            tui.stop()

    # Show post-run summary
    if mode == Mode.ctx_rm:
        result_dir = output / task / "ctx-rm" / "llamacpp" / policy.value / f"run-{run_index}"
    else:
        result_dir = output / task / mode.value / "llamacpp" / f"run-{run_index}"

    if (result_dir / "evaluation.json").exists():
        import orjson

        from ctx_rm.cli.tui import print_post_run_summary

        eval_data = orjson.loads((result_dir / "evaluation.json").read_bytes())
        agent_result = eval_data.get("agent_result", {})
        print_post_run_summary(
            console=console,
            task_id=task,
            mode=mode.value,
            passed=eval_data.get("all_passed"),
            checks_summary=eval_data.get("summary", "--"),
            prompt_tokens=agent_result.get("prompt_tokens", 0),
            completion_tokens=agent_result.get("completion_tokens", 0),
            turns=agent_result.get("turns", 0),
            evictions=agent_result.get("segments_evicted", 0),
            recalls=agent_result.get("recalls_made", 0),
            active_tokens=0,
            budget=budget,
        )
    console.print(f"  Output: [dim]{result_dir}[/dim]\n")


def _run_batch(
    policy: Policy,
    budget: int,
    output: Path,
    scorer: ScorerChoice,
    batch_mode: BatchMode,
    enable_recall: bool,
    max_turns: int,
) -> None:
    """Batch mode: all tasks x 3 modes."""
    from ctx_rm.benchmarks.loader import TaskLoader
    from ctx_rm.benchmarks.runner import BenchmarkRunner

    loader = TaskLoader(Path("docs/context_removal_benchmark_tasks.yaml"))
    task_ids = loader.list_task_ids()

    modes = ["minimal", "ctx-rm", "full"]
    total = len(task_ids) * len(modes)

    console.print()
    console.print(
        f"  [bold]Batch:[/bold] {len(task_ids)} tasks x {len(modes)} modes "
        f"= [bold]{total}[/bold] runs"
    )
    console.print(
        f"  [dim]policy={policy.value}  scorer={scorer.value}  "
        f"batch={batch_mode.value}  budget={budget:,}[/dim]"
    )
    console.print()

    completed = 0
    failed = 0
    for tid in task_ids:
        for m in modes:
            completed += 1
            label = f"  [{completed}/{total}]  {tid}  {m}  llamacpp"
            try:
                runner = BenchmarkRunner(
                    driver_name="llamacpp",
                    task_id=tid,
                    mode=m,
                    token_budget=budget,
                    policy_name=policy.value,
                    output_dir=output,
                    max_turns=max_turns,
                    enable_recall=enable_recall,
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


_KNOWN_POLICIES = frozenset(p.value for p in Policy)


def _collect_runs(run_parent: Path) -> list[Path]:
    return sorted(
        (d for d in run_parent.iterdir() if d.is_dir() and d.name.startswith("run-")),
        key=lambda p: p.name,
    )


def _aggregate_runs(
    run_dirs: list[Path],
) -> tuple[float, float, float, int, int, str, str | None]:
    from statistics import median

    import orjson

    tokens_in_list: list[float] = []
    evicted_list: list[float] = []
    peak_list: list[float] = []
    passes = 0
    total_eval = 0
    checks_str = "--"

    for rd in run_dirs:
        mp = rd / "metrics.json"
        if not mp.exists():
            continue
        data = orjson.loads(mp.read_bytes())
        s = data.get("summary", {})
        tokens_in_list.append(s.get("total_ingested_tokens", 0))
        evicted_list.append(s.get("total_evicted_tokens", 0))
        peak_list.append(s.get("peak_utilization", 0))

        ep = rd / "evaluation.json"
        if ep.exists():
            ev = orjson.loads(ep.read_bytes())
            total_eval += 1
            if ev.get("all_passed", False):
                passes += 1
            cs = ev.get("summary", "--")
            if cs != "--":
                checks_str = cs

    if not tokens_in_list:
        return 0, 0, 0, 0, 0, "--", None

    med_in = median(tokens_in_list)
    med_ev = median(evicted_list)
    med_pk = median(peak_list)
    pass_rate = f"{passes}/{total_eval}" if total_eval > 0 else None

    return med_in, med_ev, med_pk, passes, total_eval, checks_str, pass_rate


def _read_single(
    driver_dir: Path,
) -> tuple[float, float, float, int, int, str, str | None] | None:
    import orjson

    mp = driver_dir / "metrics.json"
    if not mp.exists():
        return None
    data = orjson.loads(mp.read_bytes())
    s = data.get("summary", {})
    tokens_in = s.get("total_ingested_tokens", 0)
    evicted = s.get("total_evicted_tokens", 0)
    peak = s.get("peak_utilization", 0)
    passes = 0
    total_eval = 0
    checks_str = "--"
    pass_rate: str | None = None

    ep = driver_dir / "evaluation.json"
    if ep.exists():
        ev = orjson.loads(ep.read_bytes())
        total_eval = 1
        if ev.get("all_passed", False):
            passes = 1
        checks_str = ev.get("summary", "--")
        pass_rate = f"{passes}/1"

    return float(tokens_in), float(evicted), float(peak), passes, total_eval, checks_str, pass_rate


def _format_row(
    table: Table,
    task_name: str,
    mode_name: str,
    driver_name: str,
    policy_name: str,
    med_in: float,
    med_ev: float,
    med_pk: float,
    checks_str: str,
    pass_rate: str | None,
    num_runs: int,
    total_runs: int,
) -> None:
    evict_style = ""
    if mode_name == "ctx-rm" and med_ev > 0:
        evict_style = "cyan"
    evict_display = (
        f"[{evict_style}]{int(med_ev):,}[/{evict_style}]"
        if evict_style
        else f"{int(med_ev):,}"
    )

    if med_pk > 0.9:
        peak_display = f"[red]{med_pk:.0%}[/red]"
    elif med_pk > 0.7:
        peak_display = f"[yellow]{med_pk:.0%}[/yellow]"
    else:
        peak_display = f"{med_pk:.0%}"

    if pass_rate is None:
        rate_display = "[dim]--[/dim]"
    else:
        parts = pass_rate.split("/")
        p, t = int(parts[0]), int(parts[1])
        if p == t:
            rate_display = f"[bold green]{pass_rate}[/bold green]"
        elif p > 0:
            rate_display = f"[yellow]{pass_rate}[/yellow]"
        else:
            rate_display = f"[bold red]{pass_rate}[/bold red]"

    runs_display = f"{num_runs}/{total_runs}" if total_runs > 1 else "1"

    table.add_row(
        task_name,
        mode_name,
        driver_name,
        policy_name,
        f"{int(med_in):,}",
        evict_display,
        peak_display,
        checks_str,
        rate_display,
        runs_display,
    )


@app.command()
def compare(
    results_dir: Annotated[Path, typer.Argument(
        help="Directory containing benchmark results.",
    )] = Path("./results"),
) -> None:
    """Compare benchmark results across modes and policies."""
    _quiet_logs()

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
    table.add_column("Policy")
    table.add_column("Tokens In", justify="right", style="dim")
    table.add_column("Evicted", justify="right")
    table.add_column("Peak %", justify="right")
    table.add_column("Checks", justify="right")
    table.add_column("Pass Rate", justify="center")
    table.add_column("Runs", justify="right", style="dim")

    mode_stats: dict[str, dict[str, int]] = {}
    row_count = 0

    for task_dir in sorted(results_dir.iterdir()):
        if not task_dir.is_dir():
            continue
        for mode_dir in sorted(task_dir.iterdir()):
            if not mode_dir.is_dir():
                continue
            mode_name = mode_dir.name

            for driver_dir in sorted(mode_dir.iterdir()):
                if not driver_dir.is_dir():
                    continue

                subdirs = [d for d in driver_dir.iterdir() if d.is_dir()]
                subdir_names = {d.name for d in subdirs}

                has_policy_dirs = bool(subdir_names & _KNOWN_POLICIES)

                if has_policy_dirs:
                    for policy_dir in sorted(subdirs):
                        if policy_dir.name not in _KNOWN_POLICIES:
                            continue
                        run_dirs = _collect_runs(policy_dir)
                        if not run_dirs:
                            result = _read_single(policy_dir)
                            if result is None:
                                continue
                            (
                                med_in,
                                med_ev,
                                med_pk,
                                passes,
                                total_eval,
                                checks_str,
                                pass_rate,
                            ) = result
                            num_runs, total_runs = 1, 1
                        else:
                            (
                                med_in,
                                med_ev,
                                med_pk,
                                passes,
                                total_eval,
                                checks_str,
                                pass_rate,
                            ) = _aggregate_runs(run_dirs)
                            if med_in == 0 and med_ev == 0 and med_pk == 0 and total_eval == 0:
                                continue
                            num_runs, total_runs = len(run_dirs), len(run_dirs)

                        _format_row(
                            table, task_dir.name, mode_name, driver_dir.name,
                            policy_dir.name, med_in, med_ev, med_pk, checks_str,
                            pass_rate, num_runs, total_runs,
                        )
                        row_count += 1

                        if mode_name not in mode_stats:
                            mode_stats[mode_name] = {"passed": 0, "total": 0}
                        mode_stats[mode_name]["total"] += total_eval
                        mode_stats[mode_name]["passed"] += passes

                else:
                    run_dirs = _collect_runs(driver_dir)
                    policy_display = "--"

                    if run_dirs:
                        (
                            med_in,
                            med_ev,
                            med_pk,
                            passes,
                            total_eval,
                            checks_str,
                            pass_rate,
                        ) = _aggregate_runs(run_dirs)
                        if med_in == 0 and med_ev == 0 and med_pk == 0 and total_eval == 0:
                            continue
                        num_runs, total_runs = len(run_dirs), len(run_dirs)
                    else:
                        result = _read_single(driver_dir)
                        if result is None:
                            continue
                        (
                            med_in,
                            med_ev,
                            med_pk,
                            passes,
                            total_eval,
                            checks_str,
                            pass_rate,
                        ) = result
                        num_runs, total_runs = 1, 1

                    _format_row(
                        table, task_dir.name, mode_name, driver_dir.name,
                        policy_display, med_in, med_ev, med_pk, checks_str,
                        pass_rate, num_runs, total_runs,
                    )
                    row_count += 1

                    if mode_name not in mode_stats:
                        mode_stats[mode_name] = {"passed": 0, "total": 0}
                    mode_stats[mode_name]["total"] += total_eval
                    mode_stats[mode_name]["passed"] += passes

    if row_count == 0:
        console.print(f"\n  [dim]No results found in {results_dir}[/dim]\n")
        return

    console.print()
    console.print(table)

    if mode_stats:
        console.print()
        summary = Text("  ")
        for mn in sorted(mode_stats):
            stats = mode_stats[mn]
            pct = (stats["passed"] / stats["total"] * 100) if stats["total"] > 0 else 0
            if pct == 100:
                style = "bold green"
            elif pct > 0:
                style = "yellow"
            else:
                style = "dim"
            summary.append(f"{mn}: ", style="bold")
            summary.append(f"{stats['passed']}/{stats['total']} ", style=style)
            summary.append("  ", style="dim")
        console.print(summary)
    console.print()


# ── experiment ──────────────────────────────────────────────────────────────


@app.command()
def experiment(
    config_path: Annotated[Path, typer.Argument(help="YAML experiment config file.")],
    dry_run: Annotated[bool, typer.Option(
        "--dry-run", help="Show combinations without running.",
    )] = False,
) -> None:
    """Run a multi-combination experiment from a YAML config.

    Usage:  ctx-rm experiment config.yaml
    Dry run: ctx-rm experiment config.yaml --dry-run
    """
    _quiet_logs()

    from ctx_rm.benchmarks.experiment import (
        AggregatedResult,
        ExperimentConfig,
        ExperimentRunner,
        generate_combinations,
        write_csv,
    )

    config = ExperimentConfig.from_yaml(config_path)
    combos = generate_combinations(config)

    console.print()
    console.print(
        f"  [bold]{config.name}[/bold]  "
        f"{len(config.tasks)} tasks x {len(config.modes)} modes  "
        f"{len(combos)} combinations  "
        f"{config.runs} run(s) each"
    )
    console.print()

    if dry_run:
        _print_dry_run_table(combos)
        return

    def _on_progress(current: int, total: int, combo: Any) -> None:
        console.print(
            f"  [{current}/{total}]  {combo.task_id}  {combo.mode}  "
            f"policy={combo.policy or '--'}  budget={combo.budget}  "
            f"run={combo.run_index}"
        )

    runner = ExperimentRunner(config)
    results = asyncio.run(runner.run_all(on_progress=_on_progress))

    aggregated = ExperimentRunner.aggregate(results)
    _print_experiment_table(aggregated)

    output_dir = Path(config.output_dir)
    csv_path = output_dir / f"{config.name}.csv"
    write_csv(aggregated, csv_path)
    console.print(f"\n  CSV exported: [dim]{csv_path}[/dim]\n")


def _print_dry_run_table(combos: list) -> None:
    """Print a Rich table of planned experiment combinations."""
    table = Table(
        title="Experiment Combinations (dry run)",
        show_lines=False,
        title_style="bold",
        header_style="bold cyan",
        border_style="dim",
    )
    table.add_column("#", style="dim", width=4)
    table.add_column("Task", style="bold")
    table.add_column("Mode")
    table.add_column("Policy")
    table.add_column("Budget", justify="right")
    table.add_column("Run", justify="right", style="dim")

    for i, c in enumerate(combos, 1):
        budget_display = str(c.budget) if c.budget > 0 else "auto"
        table.add_row(
            str(i),
            c.task_id,
            c.mode,
            c.policy or "--",
            budget_display,
            str(c.run_index),
        )

    console.print(table)
    console.print(f"\n  [dim]{len(combos)} combinations. Remove --dry-run to execute.[/dim]\n")


def _print_experiment_table(aggregated: list) -> None:
    """Print a Rich table of aggregated experiment results."""
    table = Table(
        title="Experiment Results",
        show_lines=False,
        title_style="bold",
        header_style="bold cyan",
        border_style="dim",
    )
    table.add_column("Task", style="bold")
    table.add_column("Mode")
    table.add_column("Policy")
    table.add_column("Budget", justify="right")
    table.add_column("Med Tokens", justify="right", style="dim")
    table.add_column("Pass Rate", justify="center")
    table.add_column("Med Evictions", justify="right")
    table.add_column("Med Recalls", justify="right")
    table.add_column("Runs", justify="right", style="dim")
    table.add_column("Errors", justify="right")

    for a in aggregated:
        # Color-code pass rate
        if a.pass_rate >= 1.0:
            rate_display = f"[bold green]{a.pass_rate:.0%}[/bold green]"
        elif a.pass_rate > 0:
            rate_display = f"[yellow]{a.pass_rate:.0%}[/yellow]"
        else:
            rate_display = f"[bold red]{a.pass_rate:.0%}[/bold red]"

        error_display = (
            f"[red]{a.num_errors}[/red]" if a.num_errors > 0 else "[dim]0[/dim]"
        )

        budget_display = str(a.budget) if a.budget > 0 else "auto"

        table.add_row(
            a.task_id,
            a.mode,
            a.policy or "--",
            budget_display,
            f"{a.median_prompt_tokens:,.0f}",
            rate_display,
            f"{a.median_eviction_count:.0f}",
            f"{a.median_recall_count:.0f}",
            str(a.num_runs),
            error_display,
        )

    console.print()
    console.print(table)

