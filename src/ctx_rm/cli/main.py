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
    driver: Annotated[str, typer.Argument(help="Agent driver: 'gemini' or 'claude'")] = "gemini",
    task: Annotated[str, typer.Option(help="Task ID from benchmark YAML")] = "CR-001",
    mode: Annotated[str, typer.Option(help="Session mode: 'minimal', 'ctx-rm', 'full'")] = "ctx-rm",
    budget: Annotated[int, typer.Option(help="Token budget for active context")] = 100_000,
    policy: Annotated[
        str, typer.Option(help="Eviction policy: 'lru', 'clock', 'budget'")
    ] = "budget",
    output: Annotated[Path, typer.Option(help="Output directory for metrics")] = Path("./results"),
    working_dir: Annotated[Path, typer.Option(help="Working directory for the agent")] = Path("."),
) -> None:
    """Run a benchmark session with the specified configuration."""
    from ctx_rm.benchmarks.runner import BenchmarkRunner

    console.print(f"[bold]Running benchmark[/bold] task={task} mode={mode} driver={driver}")
    console.print(f"  budget={budget:,} tokens, policy={policy}")

    runner = BenchmarkRunner(
        driver_name=driver,
        task_id=task,
        mode=mode,
        token_budget=budget,
        policy_name=policy,
        output_dir=output,
        working_dir=working_dir,
    )
    asyncio.run(runner.run())


@app.command()
def compare(
    results_dir: Annotated[Path, typer.Argument(help="Directory with benchmark results")] = Path(
        "./results"
    ),
) -> None:
    """Compare benchmark results across session modes."""
    import json

    console.print(f"[bold]Comparing results in {results_dir}[/bold]\n")

    table = Table(title="Benchmark Comparison")
    table.add_column("Mode", style="cyan")
    table.add_column("Tokens Ingested", justify="right")
    table.add_column("Tokens Evicted", justify="right")
    table.add_column("Peak Util %", justify="right")
    table.add_column("Avg Util %", justify="right")
    table.add_column("Evictions", justify="right")
    table.add_column("Recalls", justify="right")

    for json_file in sorted(results_dir.glob("*.json")):
        data = json.loads(json_file.read_text())
        s = data.get("summary", {})
        table.add_row(
            json_file.stem,
            f"{s.get('total_ingested_tokens', 0):,}",
            f"{s.get('total_evicted_tokens', 0):,}",
            f"{s.get('peak_utilization', 0):.1%}",
            f"{s.get('avg_utilization', 0):.1%}",
            str(s.get("eviction_count", 0)),
            str(s.get("recall_count", 0)),
        )

    console.print(table)
