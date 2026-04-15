# InfMem-Comparable Evaluation Setup

> Status note: this document predates the retirement of the synthetic benchmark
> harness. `ctx-rm bench` and `ctx-rm compare` are no longer maintained public
> commands. Treat this file as comparison-planning notes, not as a current
> runnable workflow.

This document defines how to compare `ctx-rm` against the InfMem approach
described in `infmem.md` in a way that is technically fair and reproducible.

## Why This Exists

InfMem reports strong results on ultra-long QA by combining:

- explicit control (`PRETHINK -> RETRIEVE -> WRITE`),
- bounded memory updates,
- early stopping,
- learned control policies.

`ctx-rm` targets the same core problem (bounded memory under long/noisy context)
with a different systems design:

- tiered memory (Active/Warm/Cold/Zombie),
- pluggable eviction/scoring policies,
- recall path (page-fault semantics),
- trace-replay evaluation for agentic coding traces.

The goal is not to claim architectural equivalence. The goal is to run
*comparable stress tests* where claims about quality/cost trade-offs are valid.

## Mapping: InfMem vs ctx-rm

| InfMem concept | ctx-rm analog | Notes |
|---|---|---|
| PRETHINK (sufficiency control) | Eviction trigger + scorer decision | `ctx-rm` currently does not emit a standalone STOP/RETRIEVE action token. |
| RETRIEVE (global in-document) | `search_evicted()` + `recall()` | Retrieval spans warm+cold tiers via TieredStore. |
| WRITE (bounded overwrite) | `ingest()` under token budget + eviction cycle | Bounded by `token_budget` + `headroom_ratio`. |
| Early stop | Agent loop termination / max-turn stop | Not the same policy objective yet; track as limitation. |
| Learned controller (SFT->RL) | Heuristic/Ollama/Sequential scorer + adaptive roadmap | `SequentialScorer` is the first conditional-scoring bridge. |

## Apples-to-Apples Protocol

Use this protocol for all comparison claims:

1. Fix the backbone per experiment set.
2. Run identical tasks, fixture states, and seeds.
3. Match budget bands per variant family.
4. Keep tool permissions and max turns identical.
5. Disallow external retrieval beyond local fixture/document context.

### Required Budget Bands

- `32k` equivalent
- `64k` equivalent
- `128k` equivalent
- `256k` equivalent

For current coding tasks, map these bands to practical `token_budget` values in
CLI runs and keep those values constant within each experiment.

## Metric Mapping

| InfMem-style outcome | ctx-rm metric source |
|---|---|
| Accuracy / task success | `evaluation.json -> all_passed` and per-check pass rates |
| Memory efficiency | `agent_result.prompt_tokens`, `agent_result.completion_tokens` |
| Retrieval pressure | `agent_result.recalls_made` |
| Eviction quality | `metrics.json` + derived eviction precision analysis |
| Throughput proxy | wall-clock from run logs / harness timestamps |

## Experiment Matrix

Machine-readable matrix: `docs/experiments/infmem_comparison.yaml`

Defined experiments:

- `EXP-COND-001`: Sequential (conditional) vs Heuristic (independent)
- `EXP-COST-001`: Full-context quality vs ctx-rm token cost
- `EXP-NOISE-001`: Noise-heavy scenarios where filtering can outperform full-context

## Current state

The maintained public evaluation surface now includes:

- `uv run ctx-rm eval l1 ...` for trace-replay eviction quality,
- `uv run ctx-rm eval l2 ...` for prompt-divergence replay metrics, and
- `uv run ctx-rm eval l3 ...` for a single live `AgentLoop` run.

That closes the earlier gap where only L1 was maintained. It does not yet make
this a like-for-like InfMem comparison: the public repo still lacks a dedicated
cross-paper task suite and reporting bundle that matches the InfMem paper's QA
setting.

The closest current artifact set is:

- `docs/eval/l1-postB0-baseline.md`
- `docs/eval/phaseC-implementation.md`
- `results/b0_awoc_strict.json`
- `results/b0_awoc_lenient.json`
- `results/phasec_awoc_strict.json`
- `results/phasec_awoc_lenient.json`

## Claim Gates

Use these minimum gates before claiming parity/superiority:

1. **Conditional > Independent**: sequential pass rate >= heuristic on at least 70% of tasks at <= median token usage.
2. **Quality-Cost Parity**: ctx-rm pass rate within 2 absolute points of full-context with >= 40% token reduction.
3. **Noise Advantage**: ctx-rm beats full-context on at least 2 noise-heavy tasks.

## Threats to Validity

- InfMem paper tasks are long-document QA; ctx-rm tasks are coding-agent tasks.
- InfMem includes learned control (SFT/RL); ctx-rm currently uses pluggable heuristics and optional LLM scorer.
- Early-stop behavior is not yet a directly optimized objective in ctx-rm.

These differences should always be disclosed alongside reported wins.
