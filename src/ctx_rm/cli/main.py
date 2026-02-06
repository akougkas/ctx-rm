"""ctx-rm CLI — entry point for running benchmarks and managing context."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

app = typer.Typer(
    name="ctx-rm",
    help="Context Removal for LLM agents — benchmark and evaluate eviction strategies.",
    no_args_is_help=True,
)
console = Console()


@app.command()
def info() -> None:
    """Show ctx-rm configuration and available drivers."""
    from ctx_rm import __version__

    table = Table(title=f"ctx-rm v{__version__}")
    table.add_column("Component", style="cyan")
    table.add_column("Status", style="green")

    # Check driver availability
    async def _check() -> dict[str, bool]:
        from ctx_rm.drivers.claude import ClaudeCodeDriver
        from ctx_rm.drivers.gemini import GeminiCLIDriver

        gemini = await GeminiCLIDriver().check_available()
        claude = await ClaudeCodeDriver().check_available()
        return {"gemini": gemini, "claude": claude}

    drivers = asyncio.run(_check())

    table.add_row("Gemini CLI", "✓ available" if drivers["gemini"] else "✗ not found")
    table.add_row("Claude Code", "✓ available" if drivers["claude"] else "✗ not found")
    table.add_row("Policies", "LRU, CLOCK, BudgetAware")
    table.add_row("Scorers", "Heuristic (built-in)")
    table.add_row("Store", "SQLite (built-in)")

    console.print(table)


@app.command()
def bench(
    driver: Annotated[str, typer.Option(help="Agent driver: 'gemini' or 'claude'")] = "gemini",
    task: Annotated[str, typer.Option(help="Task ID from benchmark YAML")] = "CR-001",
    mode: Annotated[str, typer.Option(help="Session mode: 'minimal', 'ctx-rm', 'full'")] = "ctx-rm",
    budget: Annotated[int, typer.Option(help="Token budget for active context")] = 100_000,
    policy: Annotated[
        str, typer.Option(help="Eviction policy: 'lru', 'clock', 'budget'")
    ] = "budget",
    output: Annotated[Path, typer.Option(help="Output directory for metrics")] = Path("./results"),
    all_tasks: Annotated[bool, typer.Option("--all", help="Run all tasks x modes x available drivers")] = False,
) -> None:
    """Run a benchmark session with the specified configuration."""
    from ctx_rm.benchmarks.runner import BenchmarkRunner

    if all_tasks:
        # Batch mode: all tasks x 3 modes x available drivers
        from ctx_rm.benchmarks.loader import TaskLoader
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
            console.print("[bold red]No drivers available.[/bold red] Install gemini or claude CLI.")
            return

        modes = ["minimal", "ctx-rm", "full"]
        total = len(task_ids) * len(modes) * len(available_drivers)
        console.print(
            f"[bold]Batch run:[/bold] {len(task_ids)} tasks x {len(modes)} modes "
            f"x {len(available_drivers)} drivers = {total} runs"
        )

        completed = 0
        for tid in task_ids:
            for m in modes:
                for d in available_drivers:
                    console.print(f"  [{completed + 1}/{total}] {tid} / {m} / {d}")
                    runner = BenchmarkRunner(
                        driver_name=d,
                        task_id=tid,
                        mode=m,
                        token_budget=budget,
                        policy_name=policy,
                        output_dir=output,
                    )
                    asyncio.run(runner.run())
                    completed += 1

        console.print(f"[bold green]Batch complete:[/bold green] {completed}/{total} runs")
        return

    # Single-run path
    console.print(f"[bold]Running benchmark[/bold] task={task} mode={mode} driver={driver}")
    console.print(f"  budget={budget:,} tokens, policy={policy}")

    runner = BenchmarkRunner(
        driver_name=driver,
        task_id=task,
        mode=mode,
        token_budget=budget,
        policy_name=policy,
        output_dir=output,
    )
    asyncio.run(runner.run())


@app.command()
def compare(
    results_dir: Annotated[Path, typer.Argument(help="Directory with benchmark results")] = Path(
        "./results"
    ),
) -> None:
    """Compare benchmark results across session modes."""
    import orjson

    console.print(f"[bold]Comparing results in {results_dir}[/bold]\n")

    table = Table(title="Benchmark Comparison")
    table.add_column("Task", style="cyan")
    table.add_column("Mode", style="cyan")
    table.add_column("Driver", style="cyan")
    table.add_column("Tokens In", justify="right")
    table.add_column("Tokens Evicted", justify="right")
    table.add_column("Peak Util %", justify="right")
    table.add_column("Checks", justify="right")
    table.add_column("Passed", justify="center")

    # Track pass/fail per mode for summary
    mode_stats: dict[str, dict[str, int]] = {}

    if not results_dir.is_dir():
        console.print(f"[red]Results directory not found:[/red] {results_dir}")
        return

    # Walk nested structure: results/{task_id}/{mode}/{driver}/
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

                # Evaluation data (optional)
                checks_str = "N/A"
                passed_str = "N/A"
                all_passed = None

                if eval_path.exists():
                    eval_data = orjson.loads(eval_path.read_bytes())
                    checks_str = eval_data.get("summary", "N/A")
                    all_passed = eval_data.get("all_passed", False)
                    passed_str = (
                        "[green]PASS[/green]" if all_passed else "[red]FAIL[/red]"
                    )

                table.add_row(
                    task_dir.name,
                    mode_dir.name,
                    driver_dir.name,
                    f"{tokens_in:,}",
                    f"{tokens_evicted:,}",
                    f"{peak_util:.1%}",
                    checks_str,
                    passed_str,
                )

                # Accumulate mode stats
                mode_name = mode_dir.name
                if mode_name not in mode_stats:
                    mode_stats[mode_name] = {"passed": 0, "total": 0}
                mode_stats[mode_name]["total"] += 1
                if all_passed is True:
                    mode_stats[mode_name]["passed"] += 1

    console.print(table)

    # Mode-aggregated summary
    if mode_stats:
        console.print("\n[bold]Mode Summary:[/bold]")
        for mode_name in sorted(mode_stats):
            stats = mode_stats[mode_name]
            pct = (stats["passed"] / stats["total"] * 100) if stats["total"] > 0 else 0
            console.print(f"  {mode_name}: {stats['passed']}/{stats['total']} passed ({pct:.0f}%)")
