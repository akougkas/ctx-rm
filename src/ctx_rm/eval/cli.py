"""CLI entry point for the eval suite: `ctx-rm eval l1 ...`

Runs the L1 mechanism tier across a corpus of traces, policies, and budgets
and prints a table with per-row bootstrap confidence intervals. All
randomness is pinned via CLI seeds so published results are reproducible.

Example:
    ctx-rm eval l1 \\
        --trace-dir ~/.claude/projects/-home-akougkas-projects-awoc \\
        --project awoc \\
        --policies oracle,random,lru,clock,budget,arc,innodb \\
        --budgets 4000,8000,16000,32000 \\
        --bypass-modes both \\
        --mode strict
"""

from __future__ import annotations

import asyncio
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
from ctx_rm.eval.l2_replay.metrics import L2Metrics, compute_replay_metrics
from ctx_rm.eval.l3_live.runner import L3RunConfig, result_to_jsonable, run_live_eval
from ctx_rm.eval.stats.bootstrap import bootstrap_mean_ci
from ctx_rm.eval.trace.claude_code import discover_transcripts, load_transcript
from ctx_rm.eval.trace.normalize import normalize
from ctx_rm.eval.trace.reference_graph import ReferenceGraph, ReferenceMode
from ctx_rm.eval.trace.schema import Trace, TraceSegmentKind

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


def _resolve_bypass_values(bypass_modes: str) -> list[str]:
    mode_tokens = _parse_csv(bypass_modes)
    if "both" in mode_tokens:
        return ["on", "off"]
    bypass_values = [m for m in mode_tokens if m in ("on", "off")]
    if not bypass_values:
        console.print("[red]--bypass-modes must name at least one of on/off/both[/red]")
        raise typer.Exit(code=2)
    return bypass_values


def _passes_filter(
    trace: Trace,
    *,
    min_segments: int,
    min_turns: int,
    min_tool_use: int,
    min_rereads: int,
) -> bool:
    if len(trace.segments) < min_segments:
        return False
    if trace.num_turns < min_turns:
        return False
    tool_uses = sum(1 for s in trace.segments if s.kind == TraceSegmentKind.TOOL_USE)
    if tool_uses < min_tool_use:
        return False
    seen: set[str] = set()
    rereads = 0
    for seg in trace.segments:
        if seg.kind == TraceSegmentKind.TOOL_USE and seg.source_file:
            if seg.source_file in seen:
                rereads += 1
            else:
                seen.add(seg.source_file)
    return rereads >= min_rereads


def _load_traces_and_graphs(
    *,
    trace_dir: Path,
    project: str,
    ref_mode: ReferenceMode,
    max_traces: int,
    min_segments: int,
    min_turns: int,
    min_tool_use: int,
    min_rereads: int,
) -> tuple[list[tuple[Trace, ReferenceGraph]], int]:
    console.print(f"[bold]Scanning {trace_dir}[/bold]")
    paths = discover_transcripts(trace_dir)
    if max_traces > 0:
        paths = paths[:max_traces]
    console.print(f"  found {len(paths)} transcripts")
    console.print(
        f"  filter: segs>={min_segments} turns>={min_turns} "
        f"tool_use>={min_tool_use} rereads>={min_rereads}"
    )

    traces_and_graphs: list[tuple[Trace, ReferenceGraph]] = []
    n_load_err = 0
    n_filtered = 0
    for path in paths:
        try:
            loaded = load_transcript(path)
            trace = normalize(loaded, project=project)
        except Exception as exc:
            n_load_err += 1
            console.print(f"  [yellow]skip {path.name}: {exc}[/yellow]")
            continue
        if not _passes_filter(
            trace,
            min_segments=min_segments,
            min_turns=min_turns,
            min_tool_use=min_tool_use,
            min_rereads=min_rereads,
        ):
            n_filtered += 1
            continue
        graph = ReferenceGraph.build(trace, ref_mode)
        traces_and_graphs.append((trace, graph))

    console.print(
        f"  filter cascade: {len(paths)} scanned -> "
        f"{n_load_err} load errors, {n_filtered} filtered, "
        f"{len(traces_and_graphs)} kept"
    )
    if not traces_and_graphs:
        console.print("[red]No usable traces after filtering.[/red]")
        raise typer.Exit(code=1)
    return traces_and_graphs, len(paths)


def _run_grid(
    *,
    traces_and_graphs: list[tuple[Trace, ReferenceGraph]],
    budget_values: list[int],
    policy_names: list[str],
    bypass_values: list[str],
) -> list[tuple[str, Trace, ReferenceGraph, object]]:
    rows: list[tuple[str, Trace, ReferenceGraph, object]] = []
    for trace, graph in traces_and_graphs:
        for budget in budget_values:
            for name in policy_names:
                factory = _POLICY_REGISTRY[name]

                def _make(g, _f=factory, _b=budget):
                    return _f(g, _b)

                for bypass in bypass_values:
                    cfg = L1RunConfig(
                        trace=trace,
                        reference_graph=graph,
                        policy_factory=_make,
                        policy_name=name,
                        token_budget=budget,
                        scorer=HeuristicScorer() if name == "budget" else None,
                        disable_bypass=(bypass == "off"),
                    )
                    rows.append((bypass, trace, graph, run_l1(cfg)))
    return rows


def _format_ci(ci, *, n: int) -> str:
    if n < 3:
        return f"{ci.mean:.3f}"
    return f"{ci.mean:.3f} [{ci.low:.3f}, {ci.high:.3f}]"


def _format_ci_int(ci, *, n: int) -> str:
    if n < 3:
        return f"{int(ci.mean)}"
    return f"{int(ci.mean)} [{int(ci.low)}, {int(ci.high)}]"


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
        "4000,8000,16000,32000", "--budgets", help="Comma-separated token budgets"
    ),
    mode: str = typer.Option("strict", "--mode", help="Reference graph mode: strict or lenient"),
    max_traces: int = typer.Option(0, "--max-traces", help="If >0, cap number of traces loaded"),
    min_segments: int = typer.Option(
        40, "--min-segments", help="Skip traces with fewer than N segments"
    ),
    min_turns: int = typer.Option(
        8, "--min-turns", help="Skip traces with fewer than N assistant turns"
    ),
    min_tool_use: int = typer.Option(
        8, "--min-tool-use", help="Skip traces with fewer than N tool_use segments"
    ),
    min_rereads: int = typer.Option(
        1, "--min-rereads", help="Skip traces with fewer than N file rereads"
    ),
    output_json: Path | None = typer.Option(
        None, "--json", help="Optional path to dump the full metric records as JSON"
    ),
    seed: int = typer.Option(0, "--seed", help="RNG seed for bootstrap + random policy"),
    bypass_modes: str = typer.Option(
        "both",
        "--bypass-modes",
        help=(
            "Comma-separated subset of {on,off,both}. 'on' runs with the "
            "default 2000-token admission bypass; 'off' raises the threshold "
            "so every segment enters Active; 'both' emits one table per mode."
        ),
    ),
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
    bypass_values = _resolve_bypass_values(bypass_modes)
    traces_and_graphs, scanned_paths = _load_traces_and_graphs(
        trace_dir=trace_dir,
        project=project,
        ref_mode=ref_mode,
        max_traces=max_traces,
        min_segments=min_segments,
        min_turns=min_turns,
        min_tool_use=min_tool_use,
        min_rereads=min_rereads,
    )

    console.print(
        f"  using {len(traces_and_graphs)} / {scanned_paths} traces "
        f"(ref mode={ref_mode.value}, seed={seed})"
    )

    run_rows = _run_grid(
        traces_and_graphs=traces_and_graphs,
        budget_values=budget_values,
        policy_names=policy_names,
        bypass_values=bypass_values,
    )
    rows: list[tuple[str, L1Metrics]] = [
        (bypass, compute_metrics(result, trace, graph))
        for bypass, trace, graph, result in run_rows
    ]

    _print_l1_table(rows, budget_values, policy_names, bypass_values, seed)

    if output_json is not None:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        with output_json.open("w") as fh:
            payload = [{"bypass": b, **m.as_row()} for b, m in rows]
            json.dump(payload, fh, indent=2)
        console.print(f"\n[green]wrote {output_json}[/green]")


@app.command("l2")
def cmd_l2(
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
        "4000,8000,16000,32000", "--budgets", help="Comma-separated token budgets"
    ),
    mode: str = typer.Option("strict", "--mode", help="Reference graph mode: strict or lenient"),
    max_traces: int = typer.Option(0, "--max-traces", help="If >0, cap number of traces loaded"),
    min_segments: int = typer.Option(
        40, "--min-segments", help="Skip traces with fewer than N segments"
    ),
    min_turns: int = typer.Option(
        8, "--min-turns", help="Skip traces with fewer than N assistant turns"
    ),
    min_tool_use: int = typer.Option(
        8, "--min-tool-use", help="Skip traces with fewer than N tool_use segments"
    ),
    min_rereads: int = typer.Option(
        1, "--min-rereads", help="Skip traces with fewer than N file rereads"
    ),
    output_json: Path | None = typer.Option(
        None, "--json", help="Optional path to dump the full metric records as JSON"
    ),
    seed: int = typer.Option(0, "--seed", help="RNG seed for bootstrap aggregation"),
    bypass_modes: str = typer.Option(
        "both",
        "--bypass-modes",
        help=(
            "Comma-separated subset of {on,off,both}. 'on' runs with the "
            "default 2000-token admission bypass; 'off' raises the threshold "
            "so every segment enters Active; 'both' emits one table per mode."
        ),
    ),
) -> None:
    """Run L2 prompt-divergence replay across a corpus and print a result table."""
    _silence_structlog()

    policy_names = _parse_csv(policies)
    unknown = set(policy_names) - set(_POLICY_REGISTRY)
    if unknown:
        console.print(f"[red]Unknown policies: {sorted(unknown)}[/red]")
        raise typer.Exit(code=2)
    budget_values = _parse_budgets(budgets)
    ref_mode = ReferenceMode(mode)
    bypass_values = _resolve_bypass_values(bypass_modes)
    traces_and_graphs, scanned_paths = _load_traces_and_graphs(
        trace_dir=trace_dir,
        project=project,
        ref_mode=ref_mode,
        max_traces=max_traces,
        min_segments=min_segments,
        min_turns=min_turns,
        min_tool_use=min_tool_use,
        min_rereads=min_rereads,
    )

    console.print(
        f"  using {len(traces_and_graphs)} / {scanned_paths} traces "
        f"(ref mode={ref_mode.value}, seed={seed})"
    )

    run_rows = _run_grid(
        traces_and_graphs=traces_and_graphs,
        budget_values=budget_values,
        policy_names=policy_names,
        bypass_values=bypass_values,
    )
    rows: list[tuple[str, L2Metrics]] = [
        (bypass, compute_replay_metrics(result, trace))
        for bypass, trace, _graph, result in run_rows
    ]
    _print_l2_table(rows, budget_values, policy_names, bypass_values, seed)

    if output_json is not None:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        with output_json.open("w") as fh:
            payload = [{"bypass": b, **m.as_row()} for b, m in rows]
            json.dump(payload, fh, indent=2)
        console.print(f"\n[green]wrote {output_json}[/green]")


def _print_l1_table(
    rows: list[tuple[str, L1Metrics]],
    budgets: list[int],
    policies: list[str],
    bypass_values: list[str],
    seed: int,
) -> None:
    """Aggregate rows by (budget, policy, bypass) and print per-cell mean ± 95% CI."""
    grouped: dict[tuple[int, str, str], list[L1Metrics]] = {}
    for bypass, row in rows:
        grouped.setdefault((row.token_budget, row.policy_name, bypass), []).append(row)

    for bypass in bypass_values:
        for budget in budgets:
            table = Table(
                title=(
                    f"L1 results  |  budget={budget}  |  bypass={bypass}  |  "
                    f"bootstrap 95% CI (seed={seed})"
                ),
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
                cell = grouped.get((budget, name, bypass), [])
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
                tok_evc = bootstrap_mean_ci(
                    [float(c.tokens_evicted) for c in cell], seed=seed
                )
                table.add_row(
                    name,
                    str(n),
                    _format_ci(prec, n=n),
                    _format_ci(erec, n=n),
                    _format_ci(ret, n=n),
                    _format_ci(ret10, n=n),
                    _format_ci(churn, n=n),
                    _format_ci_int(tok_evc, n=n),
                )
            console.print(table)


def _print_l2_table(
    rows: list[tuple[str, L2Metrics]],
    budgets: list[int],
    policies: list[str],
    bypass_values: list[str],
    seed: int,
) -> None:
    grouped: dict[tuple[int, str, str], list[L2Metrics]] = {}
    for bypass, row in rows:
        grouped.setdefault((row.token_budget, row.policy_name, bypass), []).append(row)

    for bypass in bypass_values:
        for budget in budgets:
            table = Table(
                title=(
                    f"L2 results  |  budget={budget}  |  bypass={bypass}  |  "
                    f"bootstrap 95% CI (seed={seed})"
                ),
                show_header=True,
                header_style="bold",
            )
            table.add_column("policy", style="cyan")
            table.add_column("n", justify="right")
            table.add_column("prompt_cov", justify="right")
            table.add_column("prompt_jaccard", justify="right")
            table.add_column("token_savings", justify="right")
            table.add_column("active_tok", justify="right")
            table.add_column("recorded_tok", justify="right")

            for name in policies:
                cell = grouped.get((budget, name, bypass), [])
                if not cell:
                    continue
                n = len(cell)
                coverage = bootstrap_mean_ci([c.mean_prompt_coverage for c in cell], seed=seed)
                jaccard = bootstrap_mean_ci([c.mean_prompt_jaccard for c in cell], seed=seed)
                savings = bootstrap_mean_ci([c.mean_token_savings for c in cell], seed=seed)
                active = bootstrap_mean_ci([c.mean_active_tokens for c in cell], seed=seed)
                recorded = bootstrap_mean_ci(
                    [c.mean_recorded_tokens for c in cell],
                    seed=seed,
                )
                table.add_row(
                    name,
                    str(n),
                    _format_ci(coverage, n=n),
                    _format_ci(jaccard, n=n),
                    _format_ci(savings, n=n),
                    _format_ci_int(active, n=n),
                    _format_ci_int(recorded, n=n),
                )
            console.print(table)


def _resolve_text_arg(
    *,
    value: str | None,
    path: Path | None,
    inline_name: str,
    file_name: str,
) -> str:
    if value and path:
        console.print(f"[red]Pass either {inline_name} or {file_name}, not both.[/red]")
        raise typer.Exit(code=2)
    if value:
        return value
    if path:
        return path.read_text()
    console.print(f"[red]One of {inline_name} or {file_name} is required.[/red]")
    raise typer.Exit(code=2)


@app.command("l3")
def cmd_l3(
    working_dir: Path = typer.Option(
        ...,
        "--working-dir",
        help="Working directory for the live run",
    ),
    system_prompt: str | None = typer.Option(
        None,
        "--system-prompt",
        help="Inline system prompt",
    ),
    system_file: Path | None = typer.Option(
        None,
        "--system-file",
        help="Path to a system prompt file",
    ),
    task: str | None = typer.Option(None, "--task", help="Inline task prompt"),
    task_file: Path | None = typer.Option(
        None,
        "--task-file",
        help="Path to a task prompt file",
    ),
    policy: str = typer.Option(
        "budget",
        "--policy",
        help="One of lru,clock,budget,arc,innodb",
    ),
    budget: int = typer.Option(8_000, "--budget", help="Active token budget"),
    headroom_ratio: float = typer.Option(
        0.15,
        "--headroom-ratio",
        help="Fraction of budget kept free",
    ),
    max_turns: int = typer.Option(20, "--max-turns", help="Max live agent turns"),
    min_turns: int = typer.Option(1, "--min-turns", help="Min live agent turns"),
    enable_recall: bool = typer.Option(
        False,
        "--enable-recall",
        help="Enable warm/cold recall",
    ),
    recall_top_k: int = typer.Option(1, "--recall-top-k", help="Top-K recall candidates"),
    recall_budget: int = typer.Option(3, "--recall-budget", help="Per-turn recall budget"),
    watcher_mode: str = typer.Option(
        "off",
        "--watcher-mode",
        help="One of off,interval,threshold,turn,hybrid",
    ),
    output_json: Path | None = typer.Option(
        None,
        "--json",
        help="Optional path to dump the live result as JSON",
    ),
    base_url: str | None = typer.Option(
        None,
        "--base-url",
        help="llama-server base URL override",
    ),
    temperature: float | None = typer.Option(
        None,
        "--temperature",
        help="Driver temperature override",
    ),
    max_tokens: int | None = typer.Option(
        None,
        "--max-tokens",
        help="Driver max completion tokens override",
    ),
    timeout: float | None = typer.Option(None, "--timeout", help="Driver timeout override"),
) -> None:
    """Run one live end-to-end eval session through ContextBus and AgentLoop."""
    _silence_structlog()

    if policy not in {"lru", "clock", "budget", "arc", "innodb"}:
        console.print(f"[red]Unknown L3 policy: {policy}[/red]")
        raise typer.Exit(code=2)
    if watcher_mode not in {"off", "interval", "threshold", "turn", "hybrid"}:
        console.print(f"[red]Unknown watcher mode: {watcher_mode}[/red]")
        raise typer.Exit(code=2)

    resolved_system = _resolve_text_arg(
        value=system_prompt,
        path=system_file,
        inline_name="--system-prompt",
        file_name="--system-file",
    )
    resolved_task = _resolve_text_arg(
        value=task,
        path=task_file,
        inline_name="--task",
        file_name="--task-file",
    )

    config = L3RunConfig(
        working_dir=str(working_dir),
        system_prompt=resolved_system,
        task=resolved_task,
        token_budget=budget,
        headroom_ratio=headroom_ratio,
        policy_name=policy,
        max_turns=max_turns,
        min_turns=min_turns,
        enable_recall=enable_recall,
        recall_top_k=recall_top_k,
        recall_budget=recall_budget,
        watcher_mode=watcher_mode,
        driver_base_url=base_url,
        driver_temperature=temperature,
        driver_max_tokens=max_tokens,
        driver_timeout=timeout,
    )
    result = asyncio.run(run_live_eval(config))

    table = Table(title="L3 live result", show_header=True, header_style="bold")
    table.add_column("field", style="cyan")
    table.add_column("value", justify="right")
    table.add_row("turns", str(result.turns))
    table.add_row("prompt_tokens", str(result.total_prompt_tokens))
    table.add_row("completion_tokens", str(result.total_completion_tokens))
    table.add_row("tool_calls", str(result.tool_calls_made))
    table.add_row("segments_evicted", str(result.segments_evicted))
    table.add_row("recalls", str(result.recalls_made))
    table.add_row("recall_precision", f"{result.recall_precision:.3f}")
    console.print(table)

    if output_json is not None:
        output_json.parent.mkdir(parents=True, exist_ok=True)
        output_json.write_text(json.dumps(result_to_jsonable(result), indent=2))
        console.print(f"\n[green]wrote {output_json}[/green]")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
