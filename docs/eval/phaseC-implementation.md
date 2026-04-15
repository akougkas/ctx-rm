# Post-B0 follow-on implementation

This note records the work that was still deferred at the end of the B0 polish
pass and has now been implemented in code.

## Implemented

1. `exact_quote` tightening:
   the verbatim window must now contain the gating identifier token. This
   removes the main divider/header false-positive path described in
   `phaseB-reference-graph.md`.
2. L2 replay:
   `uv run ctx-rm eval l2 ...` now computes prompt-divergence metrics against
   the recorded prefix seen at each turn boundary.
3. L3 live:
   `uv run ctx-rm eval l3 ...` now runs one live `AgentLoop` session through
   `ContextBus` and reports token, eviction, and recall stats.
4. Repo-wide lint cleanup:
   `uv run ruff check src/ctx_rm tests` is clean again.
5. Refreshed awoc reruns:
   `results/phasec_awoc_strict.json` and `results/phasec_awoc_lenient.json`
   capture the post-fix L1 reruns.

## Verification

- `uv run pytest -q`
- `uv run ruff check src/ctx_rm tests`
- `uv run ctx-rm eval l2 --help`
- `uv run ctx-rm eval l3 --help`

## Scope note

The B0 markdown artifacts remain historical documentation of the B0 graph and
baseline state. The exact-quote change and refreshed reruns described here are
follow-on work and should be read as newer than the B0 writeups, not as silent
edits to them.
