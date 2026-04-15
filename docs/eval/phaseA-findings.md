# Phase A findings: interrogating the L1 corpus and metrics

**Goal.** Before touching code, decide whether the L1 signal is real and
whether the corpus differentiates policies for the right reasons. Nothing
in Phase B is allowed to move until every number in this file is sourced
from a committed script under `scripts/audit/` and reproducible from
HEAD.

**Corpora.**
- `awoc`: `~/.claude/projects/-home-akougkas-projects-awoc` — 691 Claude
  Code transcripts, almost entirely under `<session>/subagents/`.
- `ctx-rm`: `~/.claude/projects/-home-akougkas-projects-ctx-rm` — 8
  transcripts total. Too small to carry statistical weight; used as a
  sanity corpus only.

All raw artifacts are under `docs/eval/phaseA*.{json,jsonl}` and every
numbered finding below names the script that produced it.

---

## A2 — corpus distribution and inclusion filters

Script: `scripts/audit/phaseA2_corpus_dist.py`.
Artifacts: `docs/eval/phaseA2_dist_{awoc,ctxrm}.json`.

**awoc (n=691 loaded, 0 skipped):**

| field          |    p25 |    p50 |    p75 |    p90 |     max |
| -------------- | -----: | -----: | -----: | -----: | ------: |
| segments       |     37 |     62 |     94 |    139 |     339 |
| turns          |     14 |     24 |     37 |     54 |     130 |
| tokens         | 14 733 | 29 642 | 48 041 | 69 571 | 234 407 |
| tool_use       |     14 |     25 |     38 |     54 |     130 |
| file_rereads   |      1 |      4 |     11 |     23 |      83 |

**ctx-rm (n=8):** p50 segments=75, p50 turns=32, p50 tokens≈39 k. Range
is extreme because one main-session trace has 636 segments while the
rest are 50–100 segments.

**Inclusion filter cascade on awoc:**

| filter                                                   |       n surviving |
| -------------------------------------------------------- | ----------------: |
| all loaded                                               |               691 |
| `segments >= 40`                                         |               504 |
| `segments >= 80`                                         |               237 |
| `turns >= 10`                                            |               581 |
| `tool_use >= 10`                                         |               576 |
| `file_rereads >= 1`                                      |               535 |
| `file_rereads >= 3`                                      |               415 |
| **`segs>=40 & turns>=8 & tool_use>=8 & rereads>=1`**     |           **434** |

**Decisions.**
1. **Default L1 filter:** `segments>=40 & turns>=8 & tool_use>=8 &
   file_rereads>=1`. 434 awoc traces, 5 ctx-rm traces survive. These are
   the only traces where an eviction policy can exert any force (long
   enough to pressure a budget, tool-heavy enough that bypass/re-read
   dynamics exist, at least one file re-read so the reference graph can
   fire on the file_reread rule).
2. **Useful budget grid:** `{4 000, 8 000, 16 000, 32 000}`. Median
   token count is 30 k, so 8 k pressures every trace, 32 k fits ~92 %
   of the corpus already, 128 k fits every trace and ties every policy.
   The handover's "128 k → everyone ties" result is tautological on
   this corpus; the ceiling in the old table comes from running past
   the corpus's own natural limit.
3. **ctx-rm is a sanity corpus, not a primary one.** 5 traces cannot
   support percentile bootstrap. Use awoc as the headline corpus and
   ctx-rm only for cross-corpus consistency checks.

---

## A3 — retention@k has too narrow a horizon at k=5

Script: `scripts/audit/phaseA3_retention_horizon.py`.
Artifact: `docs/eval/phaseA3_horizon_awoc.json` (awoc, 200 traces,
recommended filter).

For every turn snapshot, the "critical set" at horizon *k* is the set of
already-ingested segments whose earliest future reference falls in
`[t+1, t+k]`. If the critical set is empty, the metric trivially scores
1.0 at that snapshot and drags the mean toward 1.0 regardless of policy.

| horizon          | snapshots | trivial % | mean \|c\| | p50 \|c\| | p90 \|c\| | std of per-trace means |
| ---------------- | --------: | --------: | --------: | ------: | ------: | ---------------------: |
| k = 1            |     7 183 |     61.5% |      0.59 |       0 |       2 |                  0.223 |
| k = 3            |     7 183 |     41.5% |      1.27 |       1 |       3 |                  0.499 |
| **k = 5 (current)** | **7 183** | **33.1%** | **1.76**  | **1**   |   **4** |              **0.777** |
| k = 10           |     7 183 |     23.1% |      2.67 |       2 |       6 |                  1.391 |
| all_future       |     7 183 |     11.5% |      4.40 |       3 |       9 |                  3.144 |

**Problem with k = 5.** Mean critical set is **1.76** — below the
"size ≥ 3" threshold I set so that a 1-segment miss doesn't halve the
score. With critical size 1 or 2, every miss pushes the per-snapshot
metric from 1.0 straight to 0.5 or 0.0 with no intermediate values.
**33 %** of snapshots contribute a free 1.0, so the mean-across-snapshots
metric has a synthetic floor near 0.33 and the differences between
policies compress into a narrow band above that floor.

**Decision.** Promote **retention@all_future** (mean 4.40, trivial 11.5 %,
per-trace std 3.14) to the headline metric. Report retention@10 as a
secondary short-horizon view. **Drop retention@5.** This is exactly the
"replace the metric and regenerate every prior result table" case the
brief flagged; do it up front before any Phase B numeric work.

---

## A4 — admission bypass swallows 59 % of the corpus before any policy sees it

Script: `scripts/audit/phaseA4_admission_bypass.py`.
Artifact: `docs/eval/phaseA4_bypass_{awoc,ctxrm}.json` (awoc, 200 traces
after recommended filter).

`ContextBus._should_bypass_active` routes segments whose `source` starts
with `"file_read"` or `"tool"` and whose `token_count > admission_threshold`
(default 2 000) directly to Warm, never entering Active. In the L1 runner
`_KIND_TO_SOURCE` only maps `TOOL_RESULT → "tool"`, so bypass fires
exactly on tool_results larger than the threshold.

| threshold | segments bypassed | tokens bypassed | bypassed & referenced later | bypassed tokens referenced later |
| --------: | ----------------: | --------------: | --------------------------: | -------------------------------: |
|       500 |            14.72% |       **79.23%** |                      65.82% |                           64.21% |
|     1 000 |             9.95% |           71.93% |                      64.88% |                           63.88% |
| **2 000 (default)** | **5.80%** | **59.25%** |                  **63.82%** |                       **63.23%** |
|     4 000 |             2.59% |           39.91% |                      62.98% |                           62.78% |
|     8 000 |             0.86% |           19.61% |                      65.61% |                           63.82% |

The ctx-rm sanity corpus (n=5) shows the same pattern: 44.5 % of tokens
bypassed at the default threshold, 81.8 % of those bypassed tokens
referenced later.

**Interpretation.** At the default threshold:

- **59 % of all awoc tokens never enter Active.** The bus routes them to
  Warm on ingest. No eviction policy ever considers them.
- **63 % of bypassed tokens are referenced later** by the (already
  generous) strict reference graph. The bypass is not filtering out scan
  pollution. It is removing exactly the content the agent comes back to.
- The ~41 % of active-resident tokens is all every policy is competing
  over. Handover results like "Oracle 0.898 vs LRU 0.856 vs Budget 0.815"
  are comparisons on that minority.
- The 128 k-budget tie is an artifact: the whole 41 % fits easily, and
  the bypassed 59 % was never in the game.
- Every policy gets the same admission bypass, so the *ordering* is not
  broken. But the *story* is wrong. Today's L1 numbers do not measure
  eviction policy effectiveness; they measure "behavior on the small
  non-bypassed fraction under a bus whose admission is already making
  the primary call."

**Decision.** The L1 suite must support two columns on every published
table from here on:

1. **bypass-disabled ("pure eviction").** Set `admission_threshold` high
   enough that no segment bypasses on this corpus. This is the clean
   eviction comparison and the number the paper's "eviction policy"
   table should show.
2. **bypass-enabled ("with current bus").** Default threshold 2 000.
   Reported as the realistic integration-level number and flagged as
   measuring admission + eviction jointly.

The bypass implementation is so aggressive and so content-blind that a
smarter admission policy — one that decides based on content, not just
token count — is itself a candidate ctx-rm innovation. Today's rule
discards 63 % referenced content; anything smarter than that is a win.
This thread is deferred to Phase D.

---

## A1 — reference graph precision / recall

Script: `scripts/audit/phaseA1_reference_graph.py`.
Artifacts: `docs/eval/phaseA1_audit_{awoc,ctxrm}_strict.jsonl`.

Both corpora were audited by an LLM labeler using the same strict
rubric (strict precision rules, err-toward-FALSE_POSITIVE when
ambiguous). Labels live in each corpus's JSONL tail; counts:

| corpus  | FP records | TP | FP | ambig | FN records | missed | correct empty | ambig |
| ------- | ---------: | -: | -: | ----: | ---------: | -----: | ------------: | ----: |
| awoc    |         90 | 54 | 34 |     2 |         44 |     15 |            28 |     1 |
| ctx-rm  |         40 | 23 | 17 |     0 |         16 |      3 |            13 |     0 |
| **pooled** | **130** | **77** | **51** | **2** | **60** | **18** | **41** | **1** |

**Precision by edge kind (pooled).**

| edge kind    | TP | total decidable | precision |
| ------------ | -: | --------------: | --------: |
| file_reread  | 35 |              40 | **0.875** |
| exact_quote  | 42 |              88 | **0.477** |
| overall      | 77 |             128 | **0.602** |

**Recall lower bound on zero-incoming targets.** The FN audit only
sampled reference_capable targets that already had zero incoming strict
edges, so the number below is an upper bound on the miss rate among
that zero-edge slice, **not** a true graph-wide recall. For reference:
41 correctly-empty out of 59 decidable (0.695) on the pooled sample.

**Strict fails the 90 % precision bar.** The user's mandate was
explicit: if strict precision is under 90 %, rewrite the rules before
trusting any L1 result. 0.602 is well under, and the break is almost
entirely on `exact_quote` (0.477 pooled).

### Dominant failure modes, in order of frequency

1. **Path-prefix collisions (exact_quote FPs, ~40 records).** Source is
   a Glob/Grep/ls tool_result whose body lists file paths. Target is
   any later tool_use whose own `file_path` shares only the common
   project ancestor path (`/home/akougkas/projects/awoc/`,
   `/home/akougkas/projects/ctx-rm/`). The verbatim-20-char + 8-char
   identifier gate passes because project paths contain long
   unique-looking tokens (`akougkas`, `projects`, `awoc`, `ctx-rm`).
   Example records: awoc #14–17, #38–41, #46–52, #104–107; ctx-rm
   #21, #23–30, #41.

2. **Glob/Grep listings treated as quotable content (exact_quote FPs,
   ~10 records).** A Glob emitting "25 files listed" is structural
   metadata, not quotable text; any later read of a file whose name
   happens to appear in the listing produces an edge whose "quote" is
   just a filename. Sometimes the target file isn't even in the
   listing and the match is on the directory prefix. Example records:
   awoc #127, #131; ctx-rm #51, #55.

3. **Generic API-boilerplate matches (exact_quote FPs, ~6 records).**
   Source is a docs grep or node_modules `*.d.ts` file whose content
   is standard API surface (`pi.on("session_start")`,
   `ExtensionAPI` imports, `bun:test` imports). Target is any later
   file reusing those same tokens. Example records: awoc #24, #25, #31,
   #73, #130.

4. **Tool-error template matches (exact_quote FPs, ~3 records).**
   Source tool_result is the stock `File does not exist. Note: your
   current working directory is /home/akougkas/projects/awoc.`
   message. Any later output sharing the cwd string gets flagged.
   Example records: awoc #94, #97, #98.

5. **Directory-rooted Glob/Grep rereads (file_reread FPs, 5 records,
   awoc only).** When a Glob pattern is `**/x.ts` over root `/awoc`,
   the stored `source_file` is the root directory rather than the
   file. Two independent Globs on `/awoc` then appear as "re-reads"
   of the same "file." Example records: awoc #36, #37, #42, #43, #74.
   ctx-rm's `file_reread` sample was 10/10 clean.

6. **Discovery-by-listing missed (FNs, ~8 records).** A Bash `find` /
   Glob / `ls` tool_result lists a file path as a standalone line;
   the agent then reads that exact path. `file_reread` does not fire
   because `source_file` attribution on the listing segment is the
   search root, not the listed leaf. Example records: awoc #91, #111,
   #112, #124, #125, #145; plus #34, #78 as variants. This is the
   biggest recall hole.

7. **Paraphrased summaries of tool output missed (FNs, ~5 records).**
   Assistant text summarizes a just-seen tool_result using concept
   tokens (`156 tests pass`, `70 core modules`, `10 pp gap on
   retention`) rather than verbatim ≥20-char substrings. Example
   records: awoc #34, #66–68, #80, #102; ctx-rm #16, #17, #20.

### Implication

The strict graph has to be rewritten in Phase B1 before any L1 table is
trustworthy. The fix list below is concrete and comes straight out of
the failure modes:

- **Exclude path-prefix content from the quote check.** Strip
  project-ancestor path tokens from both source and target content
  before gating on ≥20-char verbatim + ≥8-char identifier. Candidate
  implementation: pass `project_root` into the graph builder and strip
  any substring that is a prefix of that root.
- **Exclude listing-type tool_results from being quote sources.** When
  the source tool_use's name is `LS`/`Glob`/`Grep`/`Bash (find|ls|tree)`,
  do not use its result body as a quote source. Those results produce
  discovery edges via rule 6 below, not quote edges.
- **Stoplist common SDK symbols and error templates.** Extend the
  stopword set with `session_start`, `ExtensionAPI`, `ToolCallEvent`,
  `bun:test`, `node:fs`, `File does not exist`, and the pi/Claude Code
  canonical error prefixes.
- **Require either (a) two distinct qualifying identifier tokens in
  the shared window, or (b) a single 12+ character non-path identifier.**
  A single 8-char match is too weak on this corpus.
- **Add a `file_discovery` edge kind.** If a later tool_use reads path
  P and some earlier tool_result body contains P as a standalone token
  (not a substring of a longer path), record an edge regardless of
  source_file attribution. Track discovery precision separately so the
  new kind doesn't inflate the headline number.

The paraphrase-summary FN mode (#7) is deferred: strict is supposed to
be high-precision / low-recall, and lenient already exists for the
high-recall bracket. Catching paraphrase in strict would sacrifice the
precision we are paying to recover.

---

## A5 — strict vs lenient ordering on the current (broken) graph

CLI runs (awoc, 74 traces after default filter, budgets 8 k and 32 k,
seed 0). Artifacts: `results/a5_awoc_{strict,lenient}.json`.

### Retention@5, budget 8 k

| policy | strict mean [95 % CI] | lenient mean [95 % CI] | Δ (lenient − strict) |
| ------ | :-------------------: | :--------------------: | -------------------: |
| oracle | 0.899 [0.874, 0.923]  | 0.893 [0.872, 0.913]   | −0.006 |
| lru    | 0.851 [0.824, 0.874]  | 0.863 [0.841, 0.883]   | +0.012 |
| arc    | 0.851 [0.824, 0.874]  | 0.863 [0.841, 0.883]   | +0.012 |
| innodb | 0.851 [0.824, 0.874]  | 0.863 [0.841, 0.883]   | +0.012 |
| clock  | 0.845 [0.819, 0.869]  | 0.859 [0.837, 0.879]   | +0.014 |
| random | 0.841 [0.815, 0.866]  | 0.839 [0.820, 0.859]   | −0.002 |
| budget | 0.803 [0.774, 0.831]  | 0.840 [0.819, 0.860]   | **+0.037** |

### Eviction precision, budget 8 k

| policy | strict                | lenient               |
| ------ | :-------------------: | :-------------------: |
| oracle | 0.671 [0.623, 0.719]  | 0.270 [0.232, 0.312]  |
| random | 0.716 [0.673, 0.757]  | 0.322 [0.284, 0.364]  |
| lru    | 0.669 [0.622, 0.717]  | 0.270 [0.232, 0.312]  |
| budget | 0.525 [0.462, 0.586]  | 0.188 [0.146, 0.238]  |

### Observations

1. **Budget=32 k ties everything.** Eviction recall collapses to ~0.02:
   the budget is above 92 % of the corpus so almost nothing is actually
   evicted. This reinforces A2: 32 k is near the corpus ceiling and
   should be the upper bound in the budget grid, not the middle.
2. **Retention ordering is broadly stable across modes on the strong
   policies.** Oracle leads under both. LRU/ARC/InnoDB tie each other
   under both. Clock sits just under them under both. This is weak
   evidence that the policy *ranking* is not purely an artifact of
   strict's broken exact_quote rule.
3. **BudgetAware's gap closes dramatically under lenient** (−0.037 under
   strict versus parity under lenient). BudgetAware's weakness in the
   handover number is partly a function of strict's precision problems:
   strict under-counts the "referenced again" set and then penalizes
   BudgetAware for evicting segments that (under lenient) are actually
   rare. Under lenient the critical set is larger and BudgetAware looks
   competitive with random. The real answer is unknown until the graph
   is rewritten.
4. **Eviction precision collapses under lenient.** 0.671 → 0.270 for
   oracle. Lenient labels a huge fraction of segments as "referenced
   later" via 5-gram overlap, so "evicted ∩ unreferenced" shrinks
   correspondingly. This is a metric definition issue, not a policy
   issue, and it further justifies replacing retention@5 with
   retention@all_future (A3) and rewriting the graph rules (A1).
5. **The LRU=ARC=InnoDB tie is exactly four decimal places on both
   strict and lenient runs of 74 traces.** This is the handover's
   "suspicious identity" — the three implementations are producing
   identical eviction sequences on this corpus. Phase B must either
   fix ARC/InnoDB so they react to signals agent traces actually emit,
   or drop them from the comparison.

**A5 verdict.** Mode comparison is doable but its value is limited
until the graph is fixed. The ordering signal survives on the strong
end; the magnitude signal and the BudgetAware finding do not. Treat the
above table as a baseline to regress against, not as evidence for any
paper claim.

---

## Consolidated implications for Phase B

Everything below assumes the graph is fixed first. Nothing numeric moves
until B1 lands.

### Blockers (must land together before any new L1 number is published)

1. **B1. Rewrite the reference graph rules** per the failure-mode fix
   list in A1. Rerun the precision audit and get strict precision to
   ≥ 0.90 on a held-out set of traces (do not label the same traces
   twice). Report the new precision in
   `docs/eval/phaseB-reference-graph.md` alongside the old numbers.

2. **B2. Add a bypass-disabled mode to the L1 runner** (A4). Concrete
   implementation: either raise `admission_threshold` to `sys.maxsize`
   via `L1RunConfig`, or add an explicit `disable_bypass` flag on
   ContextBus. Every published L1 table must show both columns.

3. **B3. Replace retention@5 with retention@all_future as the headline
   metric**, and add retention@10 as a secondary column (A3). Regenerate
   every prior result table; do not carry any table that still uses k=5.

4. **B4. Change the default L1 filter** to
   `segments>=40 & turns>=8 & tool_use>=8 & file_rereads>=1` and the
   default budget grid to `{4 000, 8 000, 16 000, 32 000}` (A2). 128 k
   is reported only as a "tie ceiling" row, not treated as evidence.

### Deferred until blockers land

5. **B5. Fix BudgetAware** (brief's explicit ask). Do not start until
   blockers B1–B4 land. Today's `HeuristicScorer` role weights
   (system > user > assistant > tool) penalize exactly the tool_result
   segments that turn out to be the most-referenced content on these
   traces, so the fix path is probably role-weight relearning from the
   corpus itself. Cross-validate by trace split.

6. **B6. Investigate LRU = ARC = InnoDB.** A5 confirms the identity
   at four decimals across two reference modes. Read the policies,
   decide whether to fix ARC/InnoDB's agent-trace-unfriendly dynamics
   or to drop them from the paper's main comparison table. Either
   outcome is a defensible Phase B contribution.

7. **B7. Admission policy as an innovation thread.** A4 shows that the
   current admission rule is discarding 63 % referenced content. A
   content-aware admission rule (e.g., "bypass only if the content is
   also distinct from everything already in Warm+Active") is a
   first-class research contribution. Revisit in Phase D.

Phase A is closed. Phase B begins with B1.
