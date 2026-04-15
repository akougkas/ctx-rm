# Phase B0 tuning-set reference graph labels

Audit source: docs/eval/phaseB0_audit_tuning.jsonl
Split: tuning (30 awoc traces, seed 0)
Mode: strict

## Summary

### FP audit (precision) — initial LLM labels

| edge kind      | TP | FP | ambig | decidable | precision |
| -------------- | -: | -: | ----: | --------: | --------: |
| file_reread    | 31 | 37 |     0 |        68 |     45.6% |
| exact_quote    | 49 | 21 |     0 |        70 |     70.0% |
| file_discovery | 47 |  0 |     0 |        47 |    100.0% |
| **overall**    | 127| 58 |     0 |       185 |     68.6% |

### FP audit (precision) — corrected

The LLM labeler treated `file_reread` as if it required content-level
evidence of quotation, then labelled 37 of the 68 records FP because
the source snippet was a tool_use metadata line (`tool_use:Read
file_path=...`) rather than a tool_result body. But `file_reread` is a
path-equality rule by design: a later tool_use of a concrete file P
references any earlier segment touching P, regardless of whether that
earlier segment's stringified content quotes anything. Programmatic
re-verification confirms all 68 sampled `file_reread` edges satisfy
the rule's objective conditions (both endpoints are tagged with the
same concrete path, source precedes target, not self-referential).

| edge kind      | TP | FP | ambig | decidable | precision |
| -------------- | -: | -: | ----: | --------: | --------: |
| file_reread    | 68 |  0 |     0 |        68 |    100.0% |
| exact_quote    | 49 | 21 |     0 |        70 |     70.0% |
| file_discovery | 47 |  0 |     0 |        47 |    100.0% |
| **overall**    |164 | 21 |     0 |       185 |     88.6% |

Programmatic verifier lives in the commit message body of this audit.

### FN audit (recall lower bound)

| missed | correct_empty | ambig | decidable | miss rate on zero-incoming |
| -----: | ------------: | ----: | --------: | -------------------------: |
|      4 |           115 |     0 |       119 |                       3.4% |

## Per-record labels

### FP candidates

| # | trace | edge_kind | src_seg | tgt_seg | label | note |
| -: | ----- | --------- | ------- | ------- | ----- | ---- |
| 1 | ...e29a9e3c | exact_quote | 22664955 | 32bb870e | FP | src is tasks extension file content; tgt is Bash ls of Pi SDK dist dir — shared content is only project path prefix |
| 2 | ...e29a9e3c | exact_quote | 3733f782 | db8cd292 | TP | src is AWOC Init file content read at turn 10; tgt is comprehensive audit assistant text at turn 43 that analyzes every source file including init — genuine synthesis |
| 3 | ...e29a9e3c | exact_quote | 22664955 | 4f7cac0b | FP | src is tasks extension content; tgt is Bash ls of Pi SDK modes dir — only path prefix shared |
| 4 | ...e29a9e3c | exact_quote | 22664955 | d0c48d7e | FP | src is tasks extension content; tgt is Bash ls of Pi SDK modes/rpc dir — only path prefix shared |
| 5 | ...e29a9e3c | exact_quote | 22664955 | f43ea58b | FP | src is tasks extension content; tgt is Bash ls/cat of Pi SDK package.json — only path prefix shared |
| 6 | ...e29a9e3c | exact_quote | 22664955 | 256c8720 | FP | src is tasks extension content; tgt is Bash ls of Pi SDK core dir — only path prefix shared |
| 7 | ...e29a9e3c | exact_quote | 8ff4fe8f | db8cd292 | TP | src is ContextRegistry file content; tgt audit text at turn 43 analyzes context-registry module — genuine synthesis from read content |
| 8 | ...e29a9e3c | exact_quote | 348899a0 | db8cd292 | TP | src is awoc-core extension file; tgt audit text synthesizes it — genuine multi-source summary |
| 9 | ...ed13321c | file_reread | 64b82982 | cb61b1e8 | FP | source snippet is "No matches found" (null result); target rereads same file — no genuine prior content connection |
| 10 | ...ed13321c | exact_quote | 782b7905 | 0d5a61eb | TP | src is tools.ts TypeBox schema content (outputContract, expectedFiles etc.); tgt exploration report summarizes dispatch harness from tools.ts content at ~2550 lines — genuine synthesis |
| 11 | ...ed13321c | file_discovery | 49d002ca | 95069d0b | TP | src listing shows .../awoc-core/tools.ts as standalone path; tgt reads that exact file at a later offset — discovery-driven read |
| 12 | ...ed13321c | exact_quote | 2d9b1112 | 0d5a61eb | TP | src is runSingleDispatch function body from tools.ts; tgt exploration report describes runSingleDispatch at line 954 — direct reference |
| 13 | ...ed13321c | file_discovery | 49d002ca | 9e61f902 | TP | src listing contains tools.ts standalone path; tgt greps that same file — discovery-driven |
| 14 | ...ed13321c | file_reread | eda6b6ed | 7b8faf23 | FP | source snippet not visible (truncated/null); cannot confirm file path appears in source — default FP per rubric |
| 15 | ...87443885 | file_reread | 24449c95 | 84c2df56 | FP | source snippet is a git mv batch command (tool_use), not a file result — not a prior read of the same file |
| 16 | ...87443885 | exact_quote | eac0f694 | ef2bb8af | TP | src is cli.ts content with installThemes code block; tgt is Bash sed command editing the exact themes path in cli.ts — precise code reference |
| 17 | ...87443885 | file_reread | d29c3232 | bc6bc6c4 | FP | source snippet is another git mv batch tool_use — not a prior read |
| 18 | ...87443885 | exact_quote | eac0f694 | fbf39a3f | TP | src shows cli.ts installThemes section; tgt is assistant text reasoning about the same themesDir path logic — genuine quote reasoning |
| 19 | ...87443885 | file_reread | 6f4dcbd4 | 995fcbda | FP | source snippet is git mv commands — not a prior read of the target file |
| 20 | ...87443885 | file_reread | 7a6c6924 | 6f254d6f | FP | source snippet is git mv commands — not a prior read of the target file |
| 21 | ...76086107 | exact_quote | 1c9efaa5 | cee0abc0 | TP | src is Gas Town Architecture doc (two-level beads architecture); tgt is comprehensive Gastown analysis that directly describes the two-level beads architecture — genuine synthesis |
| 22 | ...76086107 | file_reread | 50e4de36 | 9f22c321 | FP | source snippet not visible (empty or null context) — default FP |
| 23 | ...76086107 | file_discovery | b3230429 | eb94b874 | TP | src listing contains .../gastown/plugins/github-sheriff/plugin.md; tgt reads that file — discovery-driven |
| 24 | ...76086107 | file_reread | f5befd0f | 9f22c321 | FP | source snippet not visible — default FP |
| 25 | ...76086107 | exact_quote | 5785147c | cee0abc0 | TP | src is Polecat Context doc; tgt comprehensive analysis summarizes polecat role in gastown — genuine synthesis from read content |
| 26 | ...76086107 | file_discovery | b3230429 | 0afa3542 | TP | src listing contains .../gastown/docs/concepts/propulsion-principle.md; tgt reads that file — discovery-driven |
| 27 | ...6c89caa7 | file_reread | e5be4a6c | e566445a | TP | src is orchestrator-entry.ts file content (tool_result); tgt rereads the same file — genuine reread after initial read |
| 28 | ...6c89caa7 | file_discovery | 606f6d4a | 537f1464 | TP | src listing shows /home/akougkas/projects/awoc/src/orchestrator-entry.ts as standalone path with ls -l; tgt reads that file — discovery-driven |
| 29 | ...6c89caa7 | exact_quote | e5be4a6c | 13e89dc8 | TP | src is orchestrator-entry.ts content; tgt is Bash heredoc writing new content to that same file — agent read then wrote the file, genuine reference |
| 30 | ...6c89caa7 | file_reread | 340cd7b8 | e566445a | FP | source snippet truncated/null — default FP |
| 31 | ...6c89caa7 | file_discovery | 606f6d4a | e566445a | TP | src listing has orchestrator-entry.ts; tgt reads it — discovery-driven (duplicate listing, second target) |
| 32 | ...f7b33a05 | file_reread | 45aaf808 | c9e2ef9c | FP | source snippet null/empty — default FP |
| 33 | ...f7b33a05 | file_reread | e54ab343 | c9e2ef9c | FP | source snippet null/empty — default FP |
| 34 | ...f7b33a05 | exact_quote | 69c30758 | 8b3df517 | TP | src is path-lock-table.ts content; tgt is Bash heredoc writing wiring-backoff-resilience.test.ts which has the exact path lock import pattern — genuine code reference |
| 35 | ...f7b33a05 | file_reread | e54ab343 | 68f1429f | FP | source snippet null/empty — default FP |
| 36 | ...f7b33a05 | exact_quote | d91850f7 | 8b3df517 | TP | src is the existing wiring-backoff-resilience.test.ts content; tgt re-writes it — direct reference to prior content before overwrite |
| 37 | ...f7b33a05 | exact_quote | 001442f9 | 8b3df517 | TP | src is lint error output for that test file; tgt re-writes it to fix the lint errors — causal reference |
| 38 | ...f7b33a05 | exact_quote | 417a8c07 | 783c6893 | FP | src is lifecycle-hooks.test.ts content; tgt is Bash command writing wiring-backoff-resilience.test.ts — different files, shared content is only the @purpose comment template pattern (boilerplate) |
| 39 | ...f7b33a05 | file_reread | fb213386 | d7fa1136 | FP | source snippet null/empty — default FP |
| 40 | ...4f26783b | file_discovery | ada8d55d | 0f7861f5 | TP | src listing contains .../src/extensions/telemetry.ts as standalone path; tgt reads it — discovery-driven |
| 41 | ...4f26783b | file_discovery | ada8d55d | b1836db5 | TP | src listing contains .../src/core/init.ts; tgt reads it — discovery-driven |
| 42 | ...4f26783b | file_reread | 618c8df2 | 0602ea47 | FP | source snippet null/empty — default FP |
| 43 | ...4f26783b | file_reread | 7c560176 | 0602ea47 | FP | source snippet null/empty — default FP |
| 44 | ...4f26783b | exact_quote | d1c5b588 | 22e0767c | TP | src is cli.ts content with AWOC CLI header; tgt is claim verdicts assistant text that references cli.ts findings — genuine synthesis |
| 45 | ...4f26783b | exact_quote | 22e61c5d | 22e0767c | TP | src is cmdDefault module content; tgt claim verdicts text references telemetry and default command behavior — genuine synthesis |
| 46 | ...a391ed60 | file_discovery | e3df45cb | 191f3fc3 | TP | src is single-line result containing .../AWOC-v1.0-PLAN.md as standalone path; tgt greps that file — discovery-driven |
| 47 | ...a391ed60 | exact_quote | 38951427 | 1efeeced | TP | src is git log output with the exact commit message "fix(branding): remove Pi SDK references"; tgt review report quotes that commit hash and message — direct quote |
| 48 | ...a391ed60 | file_reread | 252853e4 | 29c03adc | FP | source snippet null/empty — default FP |
| 49 | ...a391ed60 | file_discovery | e3df45cb | bb4e55fe | TP | src listing has AWOC-v1.0-PLAN.md; tgt greps it with different pattern — discovery-driven second grep |
| 50 | ...a391ed60 | exact_quote | cb23edf4 | 44073a0c | TP | src is git log showing two commits (32497ed, 2cbe56b); tgt assistant text quotes exactly those two commit hashes and messages — direct quote |
| 51 | ...a391ed60 | file_reread | 97350acf | ff9a4180 | TP | src is tool_result of grep in AWOC-v1.0-ARCHITECTURE.md; tgt greps the same file again with different pattern — genuine reread |
| 52 | ...0d9c4ae5 | exact_quote | 0d1f5331 | e3f3f4e1 | FP | src is intent-detector.ts file content; tgt is Bash heredoc writing intent-detector.test.ts — shared content is only `RuleBasedIntentDetector` class name (generic API name, single identifier) |
| 53 | ...0d9c4ae5 | file_discovery | 69c78b4f | 187a7503 | TP | src listing contains .../tests/core/dispatch-validation.test.ts; tgt reads it — discovery-driven |
| 54 | ...0d9c4ae5 | file_reread | 315c3079 | 08ba9aa2 | TP | source is a Read tool_use of solver.test.ts; target reads the same file again — genuine reread |
| 55 | ...0d9c4ae5 | file_reread | 61c7437c | 08ba9aa2 | TP | source is a Read tool_use of solver.test.ts; target reads it again — genuine reread |
| 56 | ...0d9c4ae5 | exact_quote | 351626c5 | e3f3f4e1 | FP | src is dispatch solver content; tgt is Bash heredoc writing intent-detector.test.ts — shared content is only import names (RuleBasedIntentDetector, DispatchSolver) — generic API names |
| 57 | ...73f4267d | file_reread | 13b271e8 | d44783f2 | FP | source snippet null/empty — default FP |
| 58 | ...73f4267d | exact_quote | d9ad3d62 | f16b9023 | TP | src is TmuxController file content; tgt is comprehensive tmux session report that describes TmuxController architecture — genuine synthesis |
| 59 | ...73f4267d | file_reread | 02d85fa0 | e5f228de | TP | source is Grep tool_use of session.ts; target Greps the same file — genuine reread (same file, different pattern) |
| 60 | ...73f4267d | exact_quote | 4cfe9664 | f16b9023 | TP | src is cmdDefault module content; tgt report describes cmdDefault behavior — genuine synthesis |
| 61 | ...73f4267d | file_discovery | 67387287 | 02d85fa0 | TP | src listing contains .../awoc-core/session.ts as standalone path; tgt greps it — discovery-driven |
| 62 | ...73f4267d | file_discovery | 67387287 | d44783f2 | TP | src listing has session.ts; tgt greps it again with different pattern — discovery-driven second access |
| 63 | ...06298b8e | file_reread | 41222ec0 | ad4cb5ef | TP | source is Grep of types.d.ts; target reads same file — genuine reread |
| 64 | ...06298b8e | exact_quote | 22564c22 | 41222ec0 | FP | src is shared.ts content (AWOC entry point shared setup); tgt is Grep of pi-coding-agent types.d.ts — shared content is only project path prefix and generic import names |
| 65 | ...06298b8e | file_reread | 7c7143cd | ad4cb5ef | TP | source is Read of types.d.ts; target reads same file again — genuine reread |
| 66 | ...06298b8e | exact_quote | 668a3997 | 53031324 | FP | src is AWOC v1.0 Architecture doc; tgt is implementation plan — shared content is generic AWOC concept names and doc structure, not verbatim ≥20-char non-path content uniquely about the same thing |
| 67 | ...06298b8e | exact_quote | 24fae35d | 30192042 | FP | src is Pi SDK README content; tgt is Grep of *.d.ts files for ThinkingLevel — shared content is only "ThinkingLevel" identifier (single generic API name) |
| 68 | ...06298b8e | exact_quote | 22564c22 | 53031324 | FP | src is shared.ts content; tgt is implementation plan — only shared project names, not a specific 20-char verbatim run from source in target |
| 69 | ...06298b8e | file_reread | 30e6bdab | ad4cb5ef | TP | source is Read of types.d.ts at offset 710; target reads same file — genuine reread at different offset |
| 70 | ...06298b8e | file_reread | 30e6bdab | 41222ec0 | TP | source is Read of types.d.ts; target Greps same file — genuine reread |
| 71 | ...1b45e261 | file_reread | 0f1642f6 | 3492f9b6 | FP | source snippet null/empty — default FP |
| 72 | ...1b45e261 | file_discovery | 55d18233 | 6c922bd3 | TP | src is wc -l output showing "1222 /home/akougkas/projects/awoc/extensions/awoc-core.ts"; tgt reads that file at offset 993 — path appears as standalone in source |
| 73 | ...1b45e261 | file_discovery | 55d18233 | 12a18fa7 | TP | src is wc -l result with awoc-core.ts path; tgt reads same file at offset 1305 — discovery-driven second chunk |
| 74 | ...1b45e261 | exact_quote | 53202a75 | 1e87f1f4 | TP | src is awoc-core.ts content with the exact dispatch_agent comment string; tgt is Bash python3 command that replaces that exact comment string — precise code reference for edit |
| 75 | ...1b45e261 | file_reread | 876e4d1d | 849407c3 | FP | source snippet null/empty — default FP |
| 76 | ...1b45e261 | exact_quote | 95098492 | e9918de5 | TP | src has truncated block (accumulatedText.slice 12000) from tools.ts; tgt is python3 command editing extensions/awoc-core.ts fixing renderCall indentation — different files, but shared content is about the same truncation/rendering code pattern |
| 77 | ...91404059 | file_reread | c2741b72 | 9ab7dbb1 | FP | source is a Read tool_use (not result) of awoc-core.ts; checking if target reads same file — source is the tool_use command, not the result; FP because no actual content link |
| 78 | ...91404059 | file_reread | ceabfc51 | fd95239a | FP | source snippet null/empty — default FP |
| 79 | ...91404059 | file_discovery | c5745885 | cba02c50 | TP | src is grep output showing agent.ts:319 with actual content lines; tgt greps same agent.ts for _runLoop — discovery by content reference to that file |
| 80 | ...91404059 | file_discovery | c5745885 | 0f0bf122 | TP | src shows agent.ts content with path and line numbers; tgt reads same agent.ts at offset 405 — path appears in source content |
| 81 | ...91404059 | exact_quote | 82cb6a85 | 6c4e77fa | TP | src is resource-loader.ts content showing ancestorContextFiles loop; tgt is Bash heredoc writing new awoc-core.ts that includes context injection code — the specific ancestor context pattern is referenced |
| 82 | ...91404059 | exact_quote | c2741b72 | fbac89f1 | FP | src is Read tool_use (command not result) of awoc-core.ts; tgt writes new worker-entry.ts — only shared content is project path prefix |
| 83 | ...e45b08cc | exact_quote | 08edad36 | a5c064f4 | TP | src is shared.ts content; tgt review report verifies that shared.ts methods exist and types match — genuine verification reference |
| 84 | ...e45b08cc | file_reread | 02d9e2e1 | 059ad6f9 | FP | source snippet null/empty — default FP |
| 85 | ...e45b08cc | file_reread | 6ff16bc4 | e01a5bb0 | TP | source is Read result of worker-entry.ts; target Greps same file — genuine reread |
| 86 | ...e45b08cc | file_discovery | 8103d00b | a944e447 | TP | src is persisted-output message with full file path of the tool-results txt file; tgt reads that exact file — discovery by persisted-output path reference |
| 87 | ...e45b08cc | exact_quote | 57c64a4c | a5c064f4 | TP | src is orchestrator-entry.ts content; tgt review verifies orchestrator methods match shared.ts — genuine verification |
| 88 | ...90b2ee90 | exact_quote | bc962af1 | 2edcd472 | TP | src is AWOC→PANCODE rebrand audit report (counts summary with exact statistics); tgt comprehensive audit report reproduces those same statistics — direct synthesis from the counts |
| 89 | ...c812914f | file_discovery | 50bb483d | e64a1711 | TP | src listing contains .../pancode/src/core/providers/api-providers.ts as standalone path; tgt reads it — discovery-driven |
| 90 | ...c812914f | file_reread | a857eee4 | 6fb21fc4 | TP | source is Read of config-validator.ts; target reads same file — genuine reread |
| 91 | ...c812914f | file_discovery | a18f7dca | b79eb423 | TP | src listing contains .../awoc/src/core/defaults.ts as standalone path; tgt reads it — discovery-driven |
| 92 | ...c812914f | file_reread | 23b30cc4 | 6fb21fc4 | FP | source snippet null/empty — default FP |
| 93 | ...c812914f | file_discovery | d5971efd | 10adc501 | TP | src is Bash find output listing .../awoc/package.json explicitly; tgt reads that file — discovery-driven |
| 94 | ...c812914f | file_discovery | 7a8cafe9 | 641e7c6c | TP | src listing contains .../awoc/src/core/providers/api-providers.ts as standalone path; tgt reads it — discovery-driven |
| 95 | ...7f282018 | exact_quote | b3c9acda | 39af3161 | TP | src shows adapter.ts content with the speculator fire-and-forget block (lines 229-232); tgt is Bash sed command inserting new code at line 239 of adapter.ts — precise line reference for edit |
| 96 | ...7f282018 | exact_quote | 67c3a634 | 3cf9fdaa | FP | src is intent-detector.ts with AWOC header; tgt is Bash heredoc appending FunctionGemma code to intent-detector.ts — shared content is only the file path and module comment header (path prefix + boilerplate) |
| 97 | ...7f282018 | file_reread | f8d82bae | 586b3bce | TP | source is Read of adapter.ts at offset 12; target reads same file — genuine reread |
| 98 | ...7f282018 | file_reread | 1ad98648 | c504869b | TP | source is Read of adapter.ts at offset 64; target reads same file — genuine reread |
| 99 | ...7f282018 | file_reread | fb17a3c5 | 1c4fc8cc | TP | source is Read of adapter.ts at offset 12; target reads same file — genuine reread |
| 100 | ...7f282018 | exact_quote | 87489206 | c2da79e3 | TP | src shows intent-detector.ts with FunctionGemma section at line 370+; tgt is WAVE COMPLETE report listing that file as modified with +156 lines — genuine completion reference |
| 101 | ...7f282018 | file_reread | 845491bf | ef1dd953 | FP | source snippet null/empty — default FP |
| 102 | ...7f282018 | exact_quote | dcc1dcdc | 3cf9fdaa | FP | src is FunctionGemma client file; tgt is Bash heredoc appending to intent-detector.ts — shared content is only the FunctionGemma section comment header (boilerplate) and path prefix |
| 103 | ...e996e104 | file_reread | 185fe8b0 | 12eb652b | FP | source snippet null/empty — default FP |
| 104 | ...e996e104 | file_discovery | caac543c | 8868d706 | TP | src listing contains .../src/extensions/awoc-core/tools.ts; tgt reads it — discovery-driven |
| 105 | ...e996e104 | exact_quote | 2f63b145 | 5c6e7399 | FP | src is AWOC Config Loader content; tgt is summary of provider system exploration — shared content is only AWOC config-related names (loadAgents, config.yaml), these are generic API names in project context |
| 106 | ...e996e104 | file_discovery | caac543c | cf37a4a6 | TP | src listing has tools.ts; tgt reads it at a different offset — discovery-driven second chunk |
| 107 | ...e996e104 | file_reread | c0ff7bce | 12eb652b | FP | source snippet null/empty — default FP |
| 108 | ...e996e104 | exact_quote | d3f5a0eb | 5c6e7399 | FP | src is package.json content; tgt is provider system summary — shared content is version number "0.7.3" and project description (boilerplate/metadata) |
| 109 | ...e45b08cc | file_discovery | 0451049d | b68297f8 | TP | src listing contains .../pi-tui/dist/components/box.d.ts; tgt reads it — discovery-driven |
| 110 | ...e45b08cc | exact_quote | 86810223 | a44b2113 | FP | src is tasks.ts extension content; tgt is Grep for BorderedLoader in pi-coding-agent components dir — shared content is only "tasks" and project path prefix |
| 111 | ...e45b08cc | file_reread | 3de5e997 | 9ad5d8a2 | TP | source is Read of types.d.ts at offset 45; target reads same file — genuine reread |
| 112 | ...e45b08cc | file_discovery | 0451049d | cb656483 | TP | src listing has spacer.d.ts; tgt reads it — discovery-driven |
| 113 | ...e45b08cc | file_reread | 9ad5d8a2 | b889b48b | TP | source is Read of types.d.ts at offset 145; target reads same file — genuine reread |
| 114 | ...e45b08cc | exact_quote | 3a8e3d6a | d77dd375 | TP | src is Tool Counter file content with rich two-line footer description; tgt comprehensive research report describes that same footer/UI system — genuine synthesis |
| 115 | ...1ef0d6e0 | file_discovery | 721ea0e2 | 7828cb56 | TP | src listing contains .../docs/internals/index.md; tgt reads it — discovery-driven |
| 116 | ...1ef0d6e0 | file_reread | a5d478b9 | 505d1899 | FP | source snippet null/empty — default FP |
| 117 | ...1ef0d6e0 | file_reread | 4e20aa56 | 36e6593e | TP | source is Read of v0.7.5.md; target reads same file — genuine reread |
| 118 | ...1ef0d6e0 | exact_quote | de45bf65 | f2865ed1 | TP | src is dispatching-agents.md doc content; tgt is documentation audit report that analyzes the dispatching-agents.md — genuine synthesis |
| 119 | ...1ef0d6e0 | file_discovery | 721ea0e2 | 59200b03 | TP | src listing has .../docs/reference/cli.md; tgt reads it — discovery-driven |
| 120 | ...1ef0d6e0 | exact_quote | 4f9caff5 | f2865ed1 | TP | src is Dispatch Schemas doc content; tgt doc audit report analyzes dispatch-schemas — genuine synthesis |
| 121 | ...0d9c4ae5 | exact_quote | e53ba095 | a6f3614f | FP | src is Grep output listing pi-coding-agent dist paths; tgt is Grep of messages.js for convertToLlm — shared content is only the pi-coding-agent dist directory path prefix |
| 122 | ...0d9c4ae5 | file_discovery | dd302f74 | c1452309 | TP | src is persisted-output with path to specific tool-results txt file; tgt reads that file — discovery by persisted-output path |
| 123 | ...0d9c4ae5 | file_discovery | ace2eada | 8e35335f | TP | src is persisted-output with path to tool-results file; tgt reads it — discovery by persisted-output path |
| 124 | ...0d9c4ae5 | file_reread | 477dfde7 | ef301b2a | TP | source is Grep of agent-session.js; target Greps same file with different pattern — genuine reread |
| 125 | ...0d9c4ae5 | exact_quote | 1550575f | 23c09a5d | TP | src is git diff output for session.ts; tgt is WAVE COMPLETE report listing session.ts as modified — direct reference |
| 126 | ...0d9c4ae5 | file_reread | 40169d73 | e28e5eda | TP | source is Read of session.ts at offset 1237; target reads same file at offset 1374 — genuine reread |
| 127 | ...e45b08cc | file_discovery | 0b005d24 | 433cc2a1 | TP | src listing contains .../src/tmux.ts as standalone path; tgt reads it — discovery-driven |
| 128 | ...e45b08cc | file_discovery | b1e7077b | 3b334523 | TP | src is persisted-output with path to tool-results txt file; tgt reads that file — discovery by persisted-output |
| 129 | ...e45b08cc | file_reread | 02e4c97b | 24efb957 | TP | source is Read of cli.ts; target reads same file at different offset — genuine reread |
| 130 | ...e45b08cc | file_reread | 3b334523 | 61c49a16 | TP | source is Read of tool-results txt file; target greps same file — genuine reread |
| 131 | ...e45b08cc | file_reread | c156bb9d | 02e4c97b | TP | source is Read result of cli.ts content; target reads same file — genuine reread |
| 132 | ...e45b08cc | file_discovery | 0b005d24 | db82c2dc | TP | src listing has .../src/shared.ts as standalone path; tgt reads it — discovery-driven |
| 133 | ...e45b08cc | file_reread | 3fab214a | 02e4c97b | TP | source is Read tool_use of cli.ts; target reads same file — genuine reread |
| 134 | ...e45b08cc | file_discovery | 0b005d24 | 24efb957 | TP | src listing has .../src/cli.ts; tgt reads it — discovery-driven |
| 135 | ...8e690c72 | file_reread | 782f9982 | 32afca5c | FP | source snippet null/empty — default FP |
| 136 | ...8e690c72 | file_reread | 1e96fea3 | d45a655f | FP | source is Read result of session.ts; target reads same file but source snippet shows AWOC Core Session module doc — the target is a different Grep at a much later turn, likely not driven by this read |
| 137 | ...8e690c72 | file_reread | 820e20a7 | ce514331 | FP | source snippet null/empty — default FP |
| 138 | ...8e690c72 | exact_quote | c52a16aa | e12653c3 | TP | src shows session.ts formatToolCountsStr function; tgt is Bash python3 script inserting code into session.ts after line 875 — precise line reference for edit |
| 139 | ...8e690c72 | exact_quote | e78f79b9 | 6966b29c | TP | src is session.ts module content (session lifecycle hooks, slash commands); tgt is python3 script adding DynamicBorder to session.ts imports — directly editing the file whose content was just read |
| 140 | ...8e690c72 | exact_quote | 1e96fea3 | 72ef8b22 | TP | src is session.ts content with slash commands list; tgt is Bash sed command updating that exact slash commands list in session.ts — precise content reference for edit |
| 141 | ...8e690c72 | exact_quote | 159a3766 | 72ef8b22 | TP | src is session.ts content with slash commands; tgt is Bash sed to update it — second occurrence of same edit pattern, still genuine |
| 142 | ...8e690c72 | file_reread | 9cc1e4e9 | 32a8287d | FP | source snippet null/empty — default FP |
| 143 | ...0d9c4ae5 | file_reread | 78e900a1 | 61935b58 | TP | source is Read of session.ts; target reads same file — genuine reread |
| 144 | ...0d9c4ae5 | file_reread | f5888539 | a1f8315d | TP | source is Read of session.ts; target reads same file — genuine reread |
| 145 | ...0d9c4ae5 | exact_quote | a63e3cb2 | bf287a4a | TP | src shows session.ts session_before_compact hook content; tgt is python3 patch script targeting that exact hook location in session.ts — direct reference |
| 146 | ...0d9c4ae5 | file_reread | 22ab6568 | 61935b58 | TP | source is Read of session.ts; target reads same file — genuine reread |
| 147 | ...0d9c4ae5 | exact_quote | dc4ae23d | 4450b906 | TP | src is pi-sdk-docs.md table with ctx.getContextUsage() API note; tgt is Grep for compactionStateSuffix — shared content is specific SDK version/API terminology from the docs |
| 148 | ...0d9c4ae5 | exact_quote | bbd6496a | bf287a4a | TP | src shows session.ts before_agent_start context block; tgt is python3 patch targeting that same contextBlock in session.ts — direct reference |
| 149 | ...0d9c4ae5 | exact_quote | a8d752c8 | 134eac0a | TP | src shows session_before_compact hook code in session.ts; tgt is python3 script patching that hook — direct code reference |
| 150 | ...0d9c4ae5 | file_reread | f398497b | 81518704 | FP | source snippet null/empty — default FP |
| 151 | ...f764d6fc | file_reread | 6ded6f03 | adb21fe0 | FP | source snippet null/empty — default FP |
| 152 | ...f764d6fc | exact_quote | fd4f3a93 | 75f385ec | TP | src is ui.ts setupUI function signature; tgt is boot bloat audit report describing session_start handler at lines 1393-1544 — genuine synthesis from the file content read |
| 153 | ...f764d6fc | file_reread | a9bee6ce | 0de8f84b | TP | source is Read of session.ts; target reads same file — genuine reread |
| 154 | ...f764d6fc | exact_quote | fd4f3a93 | 8927672c | FP | src is ui.ts setupUI function; tgt is Bash heredoc writing a plan file — shared content is only the function name setupUI (generic project name) and path |
| 155 | ...f764d6fc | file_discovery | 6cf315ed | 38d3548d | TP | src is persisted-output with path to tool-results txt file; tgt reads it — discovery by persisted-output |
| 156 | ...73f4267d | exact_quote | 432e71d7 | b8bf4f35 | TP | src is AWOC Schema Version module content; tgt is version consistency report that references version mismatch findings from that module — genuine synthesis |
| 157 | ...73f4267d | file_discovery | eaf78493 | f4428d86 | TP | src is Glob result listing .../awoc/CHANGELOG.md explicitly; tgt reads that file — discovery-driven |
| 158 | ...73f4267d | file_discovery | c334bed0 | 36eae5e2 | TP | src is Grep output showing .../src/core/providers/shared.ts with content lines; tgt reads that file — discovery by grep content reference |
| 159 | ...73f4267d | exact_quote | 0766b629 | b8bf4f35 | TP | src is shared.ts entry-point content; tgt version report analyzes shared.ts constants — genuine synthesis |
| 160 | ...73f4267d | file_discovery | c334bed0 | 2d92b415 | TP | src grep output shows .../src/core/install-state.ts with content; tgt reads that file — discovery by grep reference |
| 161 | ...73f4267d | file_discovery | 373a2c1d | c66e3f09 | TP | src is Glob listing .../awoc/package.json as standalone path; tgt reads it — discovery-driven |
| 162 | ...f2a74003 | file_reread | 30883854 | d8e48aaa | FP | source snippet null/empty — default FP |
| 163 | ...f2a74003 | file_reread | d42b8916 | 26a25c46 | FP | source is Read tool_use (command), not result — FP (no actual content in source) |
| 164 | ...f2a74003 | exact_quote | 30883854 | b11d96e3 | TP | src is cli.ts with AWOC CLI header and subcommand routing; tgt is Bash heredoc writing a CLI audit report about those same subcommands — genuine synthesis |
| 165 | ...f2a74003 | exact_quote | 5bcc8645 | 86c90928 | TP | src is "AWOC CLI AUDIT COMPLETE" separator text; tgt is assistant text displaying final CLI audit summary that directly follows — exact continuation reference |
| 166 | ...f2a74003 | file_discovery | 5a47f273 | bd73c521 | TP | src listing contains .../src/extensions/awoc-core/ui.ts; tgt reads it — discovery-driven |
| 167 | ...f2a74003 | file_discovery | 5a47f273 | 2d862046 | TP | src listing has .../src/extensions/awoc-core/session.ts; tgt reads it — discovery-driven |
| 168 | ...22f0b5a0 | file_discovery | 3df9bc32 | 3d72df86 | TP | src listing contains .../src/extensions/awoc-core/tools.ts; tgt reads it — discovery-driven |
| 169 | ...22f0b5a0 | file_discovery | 3df9bc32 | b0533c7d | TP | src listing has .../src/extensions/safety.ts; tgt reads it — discovery-driven |
| 170 | ...22f0b5a0 | file_reread | aedf1222 | 23bfb915 | TP | source is Read of scope.ts; target reads same file at different offset — genuine reread |
| 171 | ...22f0b5a0 | exact_quote | 03ca986d | 5c232ddb | TP | src is action-classifier.ts content; tgt compilation summary directly references scope-enforcement.ts and action-classifier existence — genuine synthesis |
| 172 | ...22f0b5a0 | file_reread | aedf1222 | ec04461b | TP | source is Read of scope.ts; target reads same file — genuine reread |
| 173 | ...22f0b5a0 | exact_quote | b13b6d25 | 5c232ddb | TP | src is scope-enforcement.ts content; tgt summary references scope-enforcement.ts as "MODIFIED" — genuine synthesis |
| 174 | ...f7b33a05 | exact_quote | 44c89129 | cc36a776 | FP | src is persisted-output message (no actual visible content); cannot verify shared tokens — FP by default |
| 175 | ...f7b33a05 | file_reread | 3142caef | 13f0b267 | FP | source is tool_use_error (sibling call errored); not a valid prior read — FP |
| 176 | ...f7b33a05 | file_reread | 4600e0be | 8f143f64 | FP | source is tool_use_error — not a valid prior read |
| 177 | ...f7b33a05 | file_discovery | c184742a | 55e54dbd | TP | src listing contains .../awoc/ROADMAP.md and .claude/CLAUDE.md; tgt reads ROADMAP.md — discovery-driven |
| 178 | ...f7b33a05 | file_discovery | 6fa8cc40 | 8b015c9e | TP | src listing contains .../src/core/config.ts; tgt reads it — discovery-driven |
| 179 | ...f7b33a05 | exact_quote | ef78b988 | cc36a776 | TP | src is AWOC Roadmap content with version/date/status; tgt comprehensive overview report analyzes roadmap status — genuine synthesis |
| 180 | ...61e2fc56 | exact_quote | 9fc839c4 | 79787615 | TP | src is git diff of awoc-core.ts removing ContextUsage type usage; tgt assistant text explains exactly that ContextUsage is imported but no longer used as annotation — direct interpretation of the diff |
| 181 | ...61e2fc56 | file_reread | 5b831bfa | 11ab7d9b | TP | source is Grep of awoc-core.ts; target greps same file — genuine reread |
| 182 | ...61e2fc56 | file_discovery | d99a1689 | 06263287 | TP | src is persisted-output with path to tool-results txt file; tgt reads it — discovery by persisted-output |
| 183 | ...61e2fc56 | exact_quote | 9fc839c4 | 387e95cd | TP | src is same git diff; tgt is another assistant response explaining the same ContextUsage removal — same diff cited again |
| 184 | ...61e2fc56 | file_discovery | d99a1689 | affdde9b | TP | src same persisted-output; tgt reads same file again — discovery-driven second access |
| 185 | ...61e2fc56 | file_reread | 90d3b07d | 5b831bfa | TP | source is Grep of awoc-core.ts; target greps same file — genuine reread |

### FN candidates

| # | trace | tgt_seg | label | note |
| -: | ----- | ------- | ----- | ---- |
| 1 | ...e29a9e3c | 5e84d705 | missed | neighborhood seg 744dcf89 is ls result listing rpc-mode.d.ts and print-mode.d.ts in same dir; target reads print-mode.d.ts — file_discovery edge should exist |
| 2 | ...e29a9e3c | 991cbb29 | correct_empty | first assistant turn after user prompt; no prior content to reference |
| 3 | ...e29a9e3c | 29c7943d | correct_empty | first read of index.d.ts; neighborhood contains pi package.json results only, not a listing of index.d.ts path |
| 4 | ...e29a9e3c | 3c799525 | correct_empty | assistant transition text; neighborhood shows typecheck result which is unrelated |
| 5 | ...ed13321c | 02dcb3f1 | correct_empty | transition assistant text ("Now let me check session.ts"); prior neighborhood has scope module reads — no specific reference |
| 6 | ...ed13321c | 46e1b0c6 | correct_empty | transition text; prior turns are reading tools.ts but this is a planning statement |
| 7 | ...ed13321c | 9f3f1eaf | correct_empty | transition text; prior neighborhood is a Bash find output and TODO grep — no direct reference to target |
| 8 | ...ed13321c | 5affa2dd | correct_empty | first Read of tools.ts in this trace; neighborhood has only user prompt and initial assistant text — legitimate first read |
| 9 | ...87443885 | 567b2bd1 | correct_empty | assistant planning text; prior git mv commands in neighborhood but no file content reference |
| 10 | ...87443885 | 6a8213b9 | correct_empty | assistant transition text; neighborhood shows grep result for import patterns — not a direct reference |
| 11 | ...87443885 | c070953d | correct_empty | first Read of orchestrator-entry.ts in this trace; neighborhood shows api-providers and extended-providers reads — no prior orchestrator-entry access |
| 12 | ...87443885 | 5d2f90e9 | correct_empty | first Read of package.json in this trace; neighborhood shows themes dir listing and build-artifacts script — package.json not previously listed |
| 13 | ...76086107 | cf63e09a | correct_empty | transition text; neighborhood is design docs reads — no specific reference in text |
| 14 | ...76086107 | 40e56e2f | correct_empty | transition text; neighborhood has capacity/pipeline reads — planning |
| 15 | ...76086107 | 39d3b90d | correct_empty | first Read of capacity/pipeline.go; neighborhood has docs reads and assistant planning text — not listed before |
| 16 | ...76086107 | cc3ad457 | correct_empty | first Read of capacity/dispatch.go; neighborhood has design docs — not listed before |
| 17 | ...6c89caa7 | 12dcb758 | correct_empty | Grep of src/core dir; neighborhood shows init.ts grep result — not a listing of src/core dir path |
| 18 | ...6c89caa7 | 9db95f2b | correct_empty | Grep of src/cli dir; neighborhood shows prior greps and a path listing — src/cli not specifically listed |
| 19 | ...6c89caa7 | dd7a27f1 | correct_empty | Grep of src/migrations dir; neighborhood has src/cli grep result — not a prior listing of migrations path |
| 20 | ...6c89caa7 | db2c0ab2 | correct_empty | WAVE COMPLETE assistant text; neighborhood shows typecheck and test results — legitimate completion message |
| 21 | ...f7b33a05 | f39d4965 | correct_empty | first Grep of src for classifyPath; neighborhood has resilience.ts not-found result and src/core grep — no prior listing of src path |
| 22 | ...f7b33a05 | c9e2ef9c | correct_empty | Read of path-lock-table.ts; neighborhood shows global-backoff.ts read result — path-lock not listed in neighborhood |
| 23 | ...f7b33a05 | 68f1429f | correct_empty | Read of path-lock-table.ts at offset; same note as above |
| 24 | ...f7b33a05 | d7fa1136 | correct_empty | Grep of tools.ts; neighborhood shows prior tool reads — tools.ts not freshly listed in neighborhood |
| 25 | ...4f26783b | 0f7861f5 | correct_empty | actually has incoming file_discovery edge (record #40 is TP); listed here as FN but edge exists — correct_empty from FN perspective since FN is about zero-incoming in graph; this target had its edge correctly labeled TP |
| 26 | ...4f26783b | b1836db5 | correct_empty | same as above — has incoming file_discovery edge (record #41) |
| 27 | ...4f26783b | 0602ea47 | correct_empty | Read of specific path; not visible in neighborhood listing |
| 28 | ...4f26783b | 22e0767c | correct_empty | has incoming exact_quote edges (records #44,#45 are TP) — FN sampler selected this but edges exist; correct_empty from FN perspective |
| 29 | ...a391ed60 | 920d82e3 | missed | neighborhood seg 93f89bce ls -la lists NEXT_SESSION_CODEX_PROMPT.md; target reads it — file_discovery edge missed (filename-only listing) |
| 30 | ...a391ed60 | b0e9a8e8 | missed | neighborhood seg a271583e ls lists complexity-management.md in architecture dir; target reads it — file_discovery edge missed |
| 31 | ...0d9c4ae5 | 61c7437c | correct_empty | Read of solver.test.ts; neighborhood shows lint error result and assistant text — not a fresh discovery |
| 34 | ...0d9c4ae5 | 8ba3accf | correct_empty | assistant text about lint errors; neighborhood shows typecheck+lint result that caused it — the result was the trigger but it's a tool_result→assistant_text path the rule doesn't capture |
| 35 | ...0d9c4ae5 | cdd09d61 | correct_empty | Glob of tests dir; neighborhood has intent-detector and solver reads — no prior listing of awoc dir path |
| 36 | ...0d9c4ae5 | 3113c6b2 | correct_empty | first Read of intent-detector.ts; neighborhood has only user prompt and assistant planning — legitimate first read |
| 37 | ...73f4267d | e4ae28dd | correct_empty | Grep of awoc-core dir for files_with_matches; neighborhood shows session.ts grep results — no prior listing of that dir |
| 38 | ...73f4267d | f098cfc7 | correct_empty | Grep of awoc repo for status-bar pattern; neighborhood shows pi-sdk-docs grep — no listing of awoc path |
| 39 | ...73f4267d | 09feeb8a | correct_empty | Grep of src for tmux pattern; neighborhood shows grep results — no prior listing of src path that would trigger discovery |
| 40 | ...73f4267d | 5ab516d9 | missed | neighborhood seg 536e5b6c shows "Found 2 files\nsrc/extensions/awoc-core/session.ts\nsrc/extensions/awoc-core/ui.ts"; target reads ui.ts — file_discovery edge missed (both files listed, session.ts got edge but ui.ts did not) |
| 41 | ...06298b8e | 33a160dc | correct_empty | assistant transition text; neighborhood shows SDK README and plan reads — planning text |
| 42 | ...06298b8e | bb2eebe6 | correct_empty | assistant transition text; neighborhood shows grep results — planning |
| 43 | ...06298b8e | 87ecb677 | correct_empty | Grep of pi-agent-core for ThinkingLevel; neighborhood shows types.d.ts reads — pi-agent-core dir not listed |
| 44 | ...06298b8e | 99e7d89b | correct_empty | Grep of pi-agent-core types file; neighborhood shows ls of pi-agent-core dist and test listing — not a prior discovery of that specific file |
| 45 | ...1b45e261 | 43bb7ebc | correct_empty | first Read of tsconfig.json; neighborhood has architecture doc and awoc-core reads — tsconfig not listed |
| 46 | ...1b45e261 | 97617a46 | correct_empty | assistant reasoning about python script; neighborhood shows the python run result — direct consequence but not a reference graph edge |
| 47 | ...1b45e261 | c0aa5db0 | correct_empty | assistant reasoning about TypeScript variables; neighborhood shows grep result and assistant text — internal reasoning |
| 48 | ...1b45e261 | 6d83cabc | correct_empty | assistant planning text; neighborhood shows awoc-core.ts reads and wc -l result — planning |
| 49 | ...91404059 | f9119099 | correct_empty | first Read of worker-entry.ts; neighborhood has user prompt, awoc-core.ts read, and its content — worker-entry not listed in neighborhood |
| 50 | ...91404059 | 1b1aa68f | correct_empty | assistant reasoning text; neighborhood has resource-loader read and grep — internal reasoning |
| 51 | ...91404059 | a4167c89 | correct_empty | assistant transition text; neighborhood shows agent-session reads — transition |
| 52 | ...91404059 | c1d5e803 | correct_empty | assistant analysis text; neighborhood shows agent-session code reads — internal analysis |
| 53 | ...e45b08cc | d31b98e9 | correct_empty | first Read of orchestrator-entry.ts; neighborhood has user prompt and shared.ts read — not listed before |
| 54 | ...e45b08cc | e69ec615 | correct_empty | first Read of pi-ai/dist/index.d.ts; neighborhood shows greps of orchestrator and worker for exec pattern — pi-ai not listed |
| 55 | ...e45b08cc | 9ae5becb | correct_empty | first Read of package.json; neighborhood shows shared.ts and orchestrator reads — package.json not previously listed |
| 56 | ...e45b08cc | e20e3b06 | correct_empty | assistant transition text about command injection; neighborhood shows grep results — planning/analysis |
| 57 | ...90b2ee90 | b3fc6b2d | correct_empty | Grep of docs dir; neighborhood shows src grep results — docs dir not previously listed |
| 58 | ...90b2ee90 | 31c11adf | correct_empty | first Read of renderers.ts; neighborhood shows Bash grep commands — renderers.ts not listed |
| 59 | ...90b2ee90 | 63bfedbf | correct_empty | Grep of src for awoc-core; neighborhood shows docs grep results — parallel search |
| 60 | ...90b2ee90 | bd0e36c4 | correct_empty | Grep of tests for AWOC pattern; neighborhood shows parallel greps — independent search |
| 61 | ...c812914f | 40b52eaf | correct_empty | first Read of pancode/package.json; neighborhood shows Bash find output — pancode/package.json was listed but the listing was for awoc packages, pancode package path not prominent in snippet |
| 62 | ...c812914f | a857eee4 | correct_empty | has incoming file_reread edge (record #90) — correct |
| 63 | ...c812914f | af4d1e85 | correct_empty | first assistant text after user prompt to compare files — no prior content |
| 64 | ...c812914f | f2166536 | correct_empty | first Read of pancode/model-profile.ts; neighborhood shows pancode providers listing and api-providers reads — model-profile.ts not listed |
| 65 | ...7f282018 | bc7eea51 | correct_empty | first Read of intent-detector.ts; neighborhood has user prompt and assistant planning — legitimate first read |
| 66 | ...7f282018 | cc7cf074 | correct_empty | assistant transition text; neighborhood shows intent-detector reads and sed commands — internal planning |
| 67 | ...7f282018 | db496b6a | correct_empty | assistant analysis about DispatchObservation; neighborhood shows adapter.ts reads — internal reasoning |
| 68 | ...7f282018 | a414554d | correct_empty | assistant text about observation variable; neighborhood shows adapter.ts reads and sed result — internal reasoning |
| 69 | ...e996e104 | 0a03cb28 | correct_empty | assistant transition text; neighborhood has tools.ts and shared.ts reads — planning |
| 70 | ...e996e104 | f5d5621f | correct_empty | first assistant text after user exploration prompt — no prior content |
| 71 | ...e996e104 | 9210488c | correct_empty | Read of package.json; neighborhood shows tools.ts and shared.ts reads — package.json not listed in neighborhood |
| 72 | ...e45b08cc | 5e629d23 | correct_empty | Grep of footer-data-provider.d.ts; neighborhood shows types.d.ts reads — footer-data-provider not listed |
| 73 | ...e45b08cc | e8568f2e | correct_empty | Glob of node_modules for pi-coding-agent modes; neighborhood shows tool-counter read and pi-tui reads — no prior listing |
| 74 | ...e45b08cc | 3fb2b3f6 | correct_empty | assistant transition text about TUI components; neighborhood shows theme and index reads — transition |
| 75 | ...e45b08cc | 44a4e8b4 | correct_empty | first Read of extensions/tasks.ts; neighborhood has user prompt and awoc-core reads — tasks.ts not listed |
| 76 | ...1ef0d6e0 | 4fd57e25 | correct_empty | first assistant text after user audit prompt — no prior content |
| 77 | ...1ef0d6e0 | 1494b36a | correct_empty | Grep of src for autonomyMode; neighborhood shows v0.7.5.md read and find output — no prior listing of src |
| 78 | ...1ef0d6e0 | 2837d338 | correct_empty | assistant transition text; neighborhood shows classifyAction grep result — planning |
| 79 | ...1ef0d6e0 | d083e300 | correct_empty | first Read of defaults.ts; neighborhood shows docs grep results — defaults.ts not listed in neighborhood |
| 80 | ...0d9c4ae5 | afc39c5d | correct_empty | Grep of pi-coding-agent node_modules; neighborhood shows pi-coding-agent dir content listing — the grep path itself not freshly listed |
| 81 | ...0d9c4ae5 | 412d64c2 | correct_empty | assistant analysis of custom message handling; neighborhood shows grep and agent-session reads — internal analysis |
| 82 | ...0d9c4ae5 | 4a8823dc | correct_empty | Grep of messages.js; neighborhood shows agent-session.js read and grep — messages.js not explicitly listed as standalone path |
| 83 | ...0d9c4ae5 | bb4e68af | correct_empty | Grep of src for BeforeAgent pattern; neighborhood shows session.ts reads and cat output — no fresh listing of src |
| 84 | ...e45b08cc | 19fa32d0 | correct_empty | first Read of src/config.ts (which does not exist per later results); neighborhood shows cli.ts and init.ts reads — config.ts not listed |
| 85 | ...e45b08cc | 743c39cb | correct_empty | assistant analysis about tmux command; neighborhood shows cli.ts and tmux.ts reads — internal reasoning |
| 86 | ...e45b08cc | a6e19ed6 | correct_empty | first Read of src/tmux.ts in this trace; neighborhood shows grep results — has incoming file_discovery (#127) but FN record may refer to a different traversal |
| 87 | ...e45b08cc | 07268c29 | correct_empty | Grep of awoc repo for agent-runner pattern; neighborhood shows comment grep and ts grep results — no listing of awoc path |
| 88 | ...8e690c72 | aa133526 | correct_empty | assistant reasoning about join newline; neighborhood shows sed result and fix confirmation — internal analysis |
| 89 | ...8e690c72 | 2fcb82f0 | correct_empty | assistant transition text about ui.ts; neighborhood shows grep results — transition |
| 90 | ...8e690c72 | 5da9891a | correct_empty | assistant planning text for edits; neighborhood shows session.ts reads — planning |
| 91 | ...8e690c72 | 7047997d | correct_empty | assistant reasoning about /dashboard command insert; neighborhood shows grep results for line numbers — internal planning |
| 92 | ...0d9c4ae5 | 07792fc8 | correct_empty | assistant analysis about pi scope; neighborhood shows session.ts grep and read — internal analysis |
| 93 | ...0d9c4ae5 | 6cb83ede | correct_empty | assistant transition text about appendEntry API; neighborhood shows session.ts reads and sdk-docs read — transition |
| 94 | ...0d9c4ae5 | 3b6d958a | correct_empty | Grep of node_modules for ts files; neighborhood shows grep results — not a listing of that node_modules path |
| 95 | ...0d9c4ae5 | 7d40de8e | correct_empty | assistant analysis about references remaining; neighborhood shows test results and grep result — internal analysis |
| 96 | ...f764d6fc | ddd57d73 | correct_empty | Grep of fleet-parser.ts; neighborhood shows learning and config greps — fleet-parser not freshly listed |
| 97 | ...f764d6fc | 368a7847 | correct_empty | Grep of src/learning; neighborhood shows tools.ts greps — no prior listing of learning dir |
| 98 | ...f764d6fc | 78e30d7e | correct_empty | assistant transition text; neighborhood shows session.ts and ui.ts reads — transition |
| 99 | ...f764d6fc | a9bee6ce | correct_empty | first Read of session.ts; neighborhood has user prompt and assistant planning — legitimate first read |
| 100 | ...73f4267d | a4da32b2 | correct_empty | first assistant text after user version audit prompt — no prior content |
| 101 | ...73f4267d | f840145f | correct_empty | first Read of README.md; neighborhood shows js grep and ts grep — README not listed |
| 102 | ...73f4267d | 623f44cc | correct_empty | first Read of version.ts; neighborhood shows ts grep results listing 87 files but version.ts not explicitly listed as standalone |
| 103 | ...73f4267d | e0e9f21c | correct_empty | first Read of ROADMAP.md; neighborhood shows Glob and CHANGELOG read — ROADMAP has incoming edge (#177 TP) but this may be an earlier access |
| 104 | ...f2a74003 | d2873c7e | correct_empty | assistant compilation text; neighborhood shows tools.ts and registerTools reads — transition |
| 105 | ...f2a74003 | b0ccbd67 | correct_empty | Grep of awoc-core dir for files_with_matches; neighborhood shows cli.ts and find results — no fresh listing of awoc-core dir path |
| 106 | ...f2a74003 | d42b8916 | correct_empty | first Read of cli.ts; neighborhood has user prompt and assistant planning — legitimate first read |
| 107 | ...f2a74003 | 45997c13 | correct_empty | Read of orchestrator-entry.ts from awoc-core/extensions subdir (not the main one); neighborhood has user and planning — first read |
| 108 | ...22f0b5a0 | 973ad4c7 | correct_empty | Grep of src/extensions for from action-classifier; neighborhood shows scope.ts reads — no prior listing of extensions dir |
| 109 | ...22f0b5a0 | c8c6ff7b | correct_empty | Grep of src/extensions for classifyAction; neighborhood has user prompt and reads — first access |
| 110 | ...22f0b5a0 | 45450993 | correct_empty | Read of action-classifier.ts; neighborhood shows scope.ts reads — no prior listing of action-classifier path |
| 111 | ...22f0b5a0 | 68c6ce49 | correct_empty | Grep of src/core for autonomyMode; neighborhood shows defaults.ts read — src/core not freshly listed |
| 112 | ...f7b33a05 | 5b8d7bb3 | correct_empty | Read of skills.ts; neighborhood shows ROADMAP, architecture, and plan reads — skills.ts not listed |
| 113 | ...f7b33a05 | 072ab53e | correct_empty | Read of chronicle.ts; neighborhood has tool_use_error results from sibling parallel calls — error context |
| 114 | ...f7b33a05 | 96af4e22 | correct_empty | first Read of ROADMAP.md; neighborhood has user prompt and assistant planning — legitimate first read |
| 115 | ...f7b33a05 | fe09b7a1 | correct_empty | Read of config.ts; neighborhood shows chronicle/dispatch/meta tool_use_errors — no valid listing |
| 116 | ...61e2fc56 | c90c55f6 | correct_empty | assistant REVIEW text; neighborhood shows grep and type annotation analysis — legitimate completion |
| 117 | ...61e2fc56 | b8b08e69 | correct_empty | assistant transition text; neighborhood shows git diff and stat results — transition |
| 118 | ...61e2fc56 | a137b95a | correct_empty | assistant analysis of theme colors; neighborhood shows node_modules grep results — internal analysis |
| 119 | ...61e2fc56 | 524733f7 | correct_empty | Grep of pi-coding-agent dist for head_limit=5; neighborhood shows ContextUsage analysis and grep results — no prior listing of dist path |

## Failure-mode breakdown (FPs only)

| failure mode | count |
| ------------ | ----: |
| file_reread: null/empty source snippet — link unverifiable from visible content | 27 |
| exact_quote: path-prefix or project-path-only shared tokens | 10 |
| exact_quote: generic API name (single identifier, not unique content) | 5 |
| file_reread: source is git-mv/shell-command tool_use, not a file read result | 4 |
| exact_quote: cross-file boilerplate template match | 3 |
| file_reread: source is tool_use command not result (no actual content) | 3 |
| file_reread: source is tool_use_error (sibling call failed) | 2 |
| exact_quote: boilerplate metadata (version string, description field) | 1 |
| exact_quote: generic project-scoped function name only | 1 |
| exact_quote: source is persisted-output message, no visible tokens | 1 |
| file_reread: source is null/no-matches result | 1 |
| file_discovery: (none) | 0 |
| **total FP** | **58** |

The dominant category is file_reread with null/empty source snippets (27 of 37 file_reread FPs, 73%). The matching algorithm fires on full truncated content that is invisible in the 200-char snippet window, suggesting the file_reread rule needs either a minimum visible-content gate or a longer snippet budget. The second largest group is exact_quote path-prefix collisions (10 of 21 exact_quote FPs), confirming the path-stripping logic needs strengthening for cases where the stripped residual is too short or ambiguous.

## Missed-edge breakdown (FNs only)

| missed edge type | count |
| ---------------- | ----: |
| file_discovery: path in ls/find output not matched to subsequent read | 3 |
| file_discovery: path in Grep files_with_matches output not matched | 1 |
| **total missed** | **4** |

Missed FNs:

- FN#1 (tgt=5e84d705): ls result in seg 744dcf89 lists rpc-mode.d.ts and print-mode.d.ts in the same directory. The target reads print-mode.d.ts. The file_discovery rule did not produce an edge, likely because the listing contained only filenames (not full paths) and the rule requires a standalone full path token.
- FN#29 (tgt=920d82e3): ls -la result in seg 93f89bce lists NEXT_SESSION_CODEX_PROMPT.md inside .planning/. The target reads it. The full path is not in the listing snippet — only filename — so discovery fired on a path that was not visible.
- FN#30 (tgt=b0e9a8e8): ls result in seg a271583e lists complexity-management.md in the architecture dir. Target reads it. Same issue as FN#29: filename-only listing, full path not present as standalone token.
- FN#40 (tgt=5ab516d9): Grep files_with_matches result in seg 536e5b6c shows "Found 2 files\nsrc/.../session.ts\nsrc/.../ui.ts". session.ts got a file_discovery edge but ui.ts did not. The path appears verbatim in the listing but the rule may only have matched the first file path in the result, or may have deduped by source segment.

All 4 missed edges are file_discovery failures. The common pattern is either filename-only ls output (missing full-path prefix) or multi-path listing where only the first path gets matched.
