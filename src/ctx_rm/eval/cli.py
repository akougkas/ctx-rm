"""CLI entry point for the eval suite: `ctx-rm eval l1 ...`

Runs the L1 mechanism tier across a corpus of traces, policies, and budgets
and prints a table with per-row bootstrap confidence intervals. All
randomness is pinned via CLI seeds so published results are reproducible.

Example:
    ctx-rm eval l1 \\
        --trace-dir ~/.claude/projects/-home-akougkas-projects-ctx-rm \\
        --project ctx-rm \\
        --policies oracle,random,lru,clock,budget \\
        --budgets 8000,32000,128000 \\
        --mode strict
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from pathlib import Path

import structlog
import typer
from rich.console import Console
from rich.table import Table

from ctx_rm.core.policies.arc import ARCPolicy
from ctx_rm.core.policies.base import EvictionPolicy
from ctx_rm.core.policies.budget import BudgetAwarePolicy
from ctx_rm.core.policies.clock import ClockPolicy
from ctx_rm.core.policies.innodb import InnoDBPolicy
from ctx_rm.core.policies.lru import LRUPolicy
from ctx_rm.core.scorer import HeuristicScorer
from ctx_rm.eval.controls.oracle import OraclePolicy
from ctx_rm.eval.controls.random_policy import RandomPolicy
from ctx_rm.eval.l1_mechanism.metrics import L1Metrics, compute_metrics
from ctx_rm.eval.l1_mechanism.runner import L1RunConfig, run_l1
from ctx_rm.eval.stats.bootstrap import bootstrap_mean_ci
from ctx_rm.eval.trace.claude_code import discover_transcripts, load_transcript
from ctx_rm.eval.trace.normalize import normalize
from ctx_rm.eval.trace.reference_graph import ReferenceGraph, ReferenceMode

app = typer.Typer(help="ctx-rm evaluation suite")
console = Console()


PolicyFactory = Callable[[ReferenceGraph, int], EvictionPolicy]


_POLICY_REGISTRY: dict[str, PolicyFactory] = {
    "oracle": lambda g, b: OraclePolicy(g),
    "random": lambda g, b: RandomPolicy(seed=0),
    "lru": lambda g, b: LRUPolicy(),
    "clock": lambda g, b: ClockPolicy(),
    "budget": lambda g, b: BudgetAwarePolicy(),
    "arc": lambda g, b: ARCPolicy(capacity_tokens=b),
    "innodb": lambda g, b: InnoDBPolicy(capacity_tokens=b),
}


def _silence_structlog() -> None:
    """Muzzle structlog + stdlib logging so the CLI produces clean tables."""
    logging.basicConfig(level=logging.WARNING)
    structlog.configure(
        wrapper_class=structlog.make_filtering_bound_logger(logging.WARNING),
    )


def _parse_csv(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def _parse_budgets(value: str) -> list[int]:
    return [int(v) for v in _parse_csv(value)]


@app.command("l1")
def cmd_l1(
    trace_dir: Path = typer.Option(
        ..., "--trace-dir", help="Directory containing Claude Code .jsonl files"
    ),
    project: str = typer.Option(..., "--project", help="Project label recorded in each Trace"),
    policies: str = typer.Option(
        "oracle,random,lru,clock,budget,arc,innodb",
        "--policies",
        help="Comma-separated policies from: " + ",".join(sorted(_POLICY_REGISTRY)),
    ),
    budgets: str = typer.Option(
        "8000,32000,128000", "--budgets", help="Comma-separated token budgets"
    ),
    mode: str = typer.Option("strict", "--mode", help="Reference graph mode: strict or lenient"),
    max_traces: int = typer.Option(0, "--max-traces", help="If >0, cap number of traces loaded"),
    min_segments: int = typer.Option(
        10, "--min-segments", help="Skip traces with fewer than N segments"
    ),
    output_json: Path | None = typer.Option(
        None, "--json", help="Optional path to dump the full metric records as JSON"
    ),
    seed: int = typer.Option(0, "--seed", help="RNG seed for bootstrap + random policy"),
) -> None:
    """Run the L1 mechanism tier across a corpus and print a result table.

    Every reported delta includes a 95% bootstrap CI across traces. Rows
    with n<3 traces print the raw mean without an interval because
    percentile bootstrap on tiny samples is meaningless.
    """
    _silence_structlog()

    policy_names = _parse_csv(policies)
    unknown = set(policy_names) - set(_POLICY_REGISTRY)
    if unknown:
        console.print(f"[red]Unknown policies: {sorted(unknown)}[/red]")
        raise typer.Exit(code=2)
    budget_values = _parse_budgets(budgets)
    ref_mode = ReferenceMode(mode)

    console.print(f"[bold]Scanning {trace_dir}[/bold]")
    paths = discover_transcripts(trace_dir)
    if max_traces > 0:
        paths = paths[:max_traces]
    console.print(f"  found {len(paths)} transcripts")

    traces_and_graphs: list[tuple] = []
    for p in paths:
        try:
            loaded = load_transcript(p)
            trace = normalize(loaded, project=project)
        except Exception as exc:
            console.print(f"  [yellow]skip {p.name}: {exc}[/yellow]")
            continue
        if len(trace.segments) < min_segments:
            continue
        graph = ReferenceGraph.build(trace, ref_mode)
        traces_and_graphs.append((trace, graph))

    if not traces_and_graphs:
        console.print("[red]No usable traces after filtering.[/red]")
        raise typer.Exit(code=1)

    console.print(
        f"  using {len(traces_and_graphs)} traces (ref mode={ref_mode.value}, seed={seed})"
    )

    rows: list[L1Metrics] = []
    for trace, graph in traces_and_graphs:
        for budget in budget_values:
            for name in policy_names:
                factory = _POLICY_REGISTRY[name]

                # Bind name/budget/factory into the lambda's default args so
                # B023 stays quiet and each config captures the right policy.
                def _make(g, _f=factory, _b=budget):
                    return _f(g, _b)

                cfg = L1RunConfig(
                    trace=trace,
                    reference_graph=graph,
                    policy_factory=_make,
                    policy_name=name,
                    token_budget=budget,
                    scorer=HeuristicScorer() if name == "budget" else None,
                )
                result = run_l1(cfg)
                rows.append(compute_metrics(result, trace, graph))

    _print_table(rows, budget_values, policy_names, seed)

    if output_json is not None:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        with output_json.open("w") as fh:
            json.dump([r.as_row() for r in rows], fh, indent=2)
        console.print(f"\n[green]wrote {output_json}[/green]")


def _print_table(
    rows: list[L1Metrics],
    budgets: list[int],
    policies: list[str],
    seed: int,
) -> None:
    """Aggregate rows by (budget, policy) and print per-cell mean ± 95% CI."""
    grouped: dict[tuple[int, str], list[L1Metrics]] = {}
    for row in rows:
        grouped.setdefault((row.token_budget, row.policy_name), []).append(row)

    for budget in budgets:
        table = Table(
            title=f"L1 results  |  budget={budget}  |  bootstrap 95% CI (seed={seed})",
            show_header=True,
            header_style="bold",
        )
        table.add_column("policy", style="cyan")
        table.add_column("n", justify="right")
        table.add_column("precision", justify="right")
        table.add_column("eviction recall", justify="right")
        table.add_column("retention", justify="right")
        table.add_column("retention@10", justify="right")
        table.add_column("churn", justify="right")
        table.add_column("tok_evc", justify="right")

        for name in policies:
            cell = grouped.get((budget, name), [])
            if not cell:
                continue
            n = len(cell)
            prec = bootstrap_mean_ci([c.eviction_precision for c in cell], seed=seed)
            erec = bootstrap_mean_ci([c.eviction_recall for c in cell], seed=seed)
            ret = bootstrap_mean_ci(
                [c.critical_segment_retention for c in cell], seed=seed
            )
            ret10 = bootstrap_mean_ci(
                [c.critical_segment_retention_k10 for c in cell], seed=seed
            )
            churn = bootstrap_mean_ci([c.churn_rate for c in cell], seed=seed)
            tok_evc = bootstrap_mean_ci([float(c.tokens_evicted) for c in cell], seed=seed)

            def fmt(ci, _n=n) -> str:
                if _n < 3:
                    return f"{ci.mean:.3f}"
                return f"{ci.mean:.3f} [{ci.low:.3f}, {ci.high:.3f}]"

            def fmt_int(ci, _n=n) -> str:
                if _n < 3:
                    return f"{int(ci.mean)}"
                return f"{int(ci.mean)} [{int(ci.low)}, {int(ci.high)}]"

            table.add_row(
                name,
                str(n),
                fmt(prec),
                fmt(erec),
                fmt(ret),
                fmt(ret10),
                fmt(churn),
                fmt_int(tok_evc),
            )
        console.print(table)


def main() -> None:
    app()


if __name__ == "__main__":
    main()
