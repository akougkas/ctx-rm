# Phase B0 reference-graph precision — post-rewrite numbers

Script: `scripts/audit/phaseA1_reference_graph.py`
Split definition: `docs/eval/phaseB0_validation_split.json`
Tuning artifacts: `docs/eval/phaseB0_audit_tuning.jsonl`, `docs/eval/phaseB0_tuning_labels.md`
Validation artifacts: `docs/eval/phaseB0_audit_validation.jsonl`, `docs/eval/phaseB0_validation_labels.md`

## Headline

| split | traces | edges | FP samples | precision |
| ----- | -----: | ----: | ---------: | --------: |
| Phase A1 pooled (pre-B0) | 12 awoc + 6 ctx-rm | — |       130 |     0.602 |
| Phase B0 tuning  | 30 awoc |  2823 |       185 |     0.886 |
| Phase B0 validation | 60 awoc |  6441 |       338 |     0.710 |

Per-rule precision:

| rule            | A1 pooled | B0 tuning | B0 validation | target | verdict |
| --------------- | --------: | --------: | ------------: | -----: | ------- |
| file_reread     |     0.875 |     1.000 |         1.000 |   0.90 | passes  |
| exact_quote     |     0.477 |     0.700 |         0.236 |   0.90 | fails   |
| file_discovery  | n/a (new) |     1.000 |         0.951 |   0.90 | passes  |
| overall         |     0.602 |     0.886 |         0.710 |   0.90 | mixed   |

Recall lower bound on zero-incoming targets:

| split        | missed | correct_empty | decidable | miss rate |
| ------------ | -----: | ------------: | --------: | --------: |
| tuning       |      4 |           115 |       119 |    0.034  |
| validation   |      6 |           174 |       180 |    0.033  |

The file_discovery edge kind closed the "discovery-by-listing" recall
gap from Phase A1 almost entirely. Both miss rates are in the noise.

## The labeler-error correction on file_reread

The initial LLM labeler on the tuning set scored file_reread at 45.6%
because it demanded content-level quote evidence for every edge and
marked 37 of 68 records FP when the source snippet was a tool_use
metadata line (`tool_use:Read\nfile_path=...`) rather than a
tool_result body.

file_reread is a **path-equality rule** by design. A later tool_use
with concrete `source_file` P references any earlier segment touching
P, regardless of whether that earlier segment's stringified content
contains quotable text. A programmatic verifier — reconstructing the
same invariants the rule enforces (both endpoints tagged with the same
concrete path, source event_index before target, no self-edge) —
confirms 68 of 68 tuning records and 133 of 133 validation records
satisfy the objective conditions.

Corrected tuning file_reread precision: 100.0%.
Corrected validation file_reread precision: 100.0%.
(The 92.5% the validation labeler reported falls to the same confusion
on 10 of the 133 records despite explicit guidance in the rubric.)

## Why exact_quote collapses on validation

Tuning exact_quote: 70.0%. Validation exact_quote: 23.6%. The rule's
mechanism is unchanged across splits, so the collapse is a
distributional shift.

Direct inspection of validation FPs reveals the dominant mode: the
validation slice is heavy in `Read file → Bash heredoc writing a new
file` workflows (awoc scaffolding and refactors). The rewritten
exact_quote rule's two-stage gate — an ≥8-char non-stopword identifier
token in both bodies, then any ≥20-char verbatim run anywhere in the
stripped source — is satisfied by boilerplate common to both files:

- **Divider lines.** `====================` (20 chars of `=`) appears
  in multiple awoc source files. The gating token is a real
  identifier like `Dispatch`, but the verbatim run that seals the
  match is a separator.
- **Common headers.** `/**\n * AWOC `, `#!/usr/bin/env bun`, file
  banners that the agent copies across related files.
- **Import lines.** `} from "node:fs"`, `import { describe, expect,
  test } from "bun:test"` — identical across many test files.

Each of these passes the two-stage gate mechanically but does not
represent the agent actually referencing specific prior content. They
are structural artifacts of bulk-scaffolding workflows.

A fix exists in principle — require the ≥20-char verbatim run to
**contain** the gating identifier token, so dividers and shared
headers stop qualifying. On a 15-record sample of validation FPs this
kills 10/15 without breaking the existing positive test (the
`authenticate_user_with_token` case passes because a window containing
that token is verbatim-shared). **We did not apply this fix during
Phase B0.** At that point the B0 evaluation discipline forbade
re-tuning after looking at the validation split, and the
tuning-to-validation gap (17.6 pp) was far above the threshold where
the correct move was "accept validation and do not iterate". Applying
a new tighten-up there would have contaminated the held-out
evaluation.

The candidate fix is documented for Phase C. If we choose to rerun
the audit on a freshly-sampled held-out split, that fix should ship
first.

## Shipping decision

**File_reread and file_discovery pass the 0.90 bar with clean margins
on both splits.** They carry the main oracle signal for L1 metrics:
"did the agent re-read a file it touched" and "did the agent read a
file it discovered via listing" are the dominant reference patterns
in the awoc corpus.

**exact_quote does not pass.** It remains in the graph but its signal
should be interpreted with caution. A conservative reading of the
post-B0 strict graph treats file_reread and file_discovery as the
primary labels and weights exact_quote as supplementary. No L1 metric
code change is required: the current retention/eviction metrics
aggregate over all edges uniformly, and exact_quote's FPs are drowned
out on awoc because file_reread dominates the edge mix (5319 of 6441
validation edges are file_reread).

For the paper we report pooled precision 0.710 with a per-rule table
and the failure-mode writeup above. We do not claim 0.90.

## Inputs feeding Phase C

- exact_quote tightening: require the 20-char verbatim run to contain
  the gating identifier token; re-audit on a fresh held-out split.
- Consider whether the reference graph for agent traces needs a
  dedicated "file rewrite" edge kind (later tool_use writes the same
  path that was read earlier) separate from exact_quote, since the
  rewrite pattern is both common and poorly modeled by content-match
  rules.
