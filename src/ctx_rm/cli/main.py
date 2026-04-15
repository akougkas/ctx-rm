"""ctx-rm CLI.

Top-level commands:

- `ctx-rm info` — show runtime status and configured defaults.
- `ctx-rm eval ...` — run the evaluation suite (see `ctx_rm.eval.cli`).

The legacy `bench`, `experiment`, `analyze`, `compare`, and `tasks` commands
were removed when the synthetic-benchmark harness under `ctx_rm.benchmarks`
was retired. The trace-replay evaluation suite under `ctx_rm.eval` replaces
them.
"""

from __future__ import annotations

import asyncio
import logging

import structlog
import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from ctx_rm.eval.cli import app as _eval_app


def _quiet_logs() -> None:
    logging.basicConfig(level=logging.WARNING)
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING),
    )


app = typer.Typer(
    name="ctx-rm",
    help="Virtual-memory semantics for LLM context windows.",
    no_args_is_help=True,
    rich_markup_mode="rich",
    pretty_exceptions_enable=False,
)
app.add_typer(_eval_app, name="eval", help="Evaluation suite (L1 / L2 / L3)")

console = Console()


@app.command()
def info() -> None:
    """Show runtime status: version, driver availability, configured defaults."""
    _quiet_logs()
    from ctx_rm import __version__
    from ctx_rm.config import CtxRmConfig

    config = CtxRmConfig()

    async def _check() -> dict[str, bool]:
        from ctx_rm.drivers.llamacpp import LlamaCppDriver

        try:
            ok = await LlamaCppDriver(base_url=config.llama_base_url).check_available()
        except Exception:
            ok = False
        return {"llamacpp": ok}

    drivers = asyncio.run(_check())

    grid = Table.grid(padding=(0, 2))
    grid.add_column(style="dim", min_width=18)
    grid.add_column()

    grid.add_row("Version", f"[bold]{__version__}[/bold]")
    grid.add_row("", "")
    for name, available in drivers.items():
        status = "[green]available[/green]" if available else "[dim]not found[/dim]"
        grid.add_row(f"Driver: {name}", status)
    grid.add_row("", "")
    grid.add_row("Policies", "lru  clock  budget  arc  innodb")
    grid.add_row("Scorer", f"[bold]{config.scorer}[/bold]")
    grid.add_row("Store", "SQLite + TieredStore [dim](warm/cold/zombie)[/dim]")
    grid.add_row("", "")
    grid.add_row("Token budget", f"{config.token_budget:,}")
    grid.add_row("LLM base URL", config.llama_base_url)

    console.print(Panel(grid, title="[bold]ctx-rm[/bold]", border_style="blue", padding=(1, 2)))


def main() -> None:
    app()


if __name__ == "__main__":
    main()
