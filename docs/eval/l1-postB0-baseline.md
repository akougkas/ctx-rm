# L1 post-B0 baseline — awoc, 131 traces

On 131 agent traces across four budgets, two reference modes, and two
admission settings, LRU, ARC, and InnoDB produce bit-identical eviction
sequences in every cell while oracle retains a 10 to 16 percentage-point
headroom at working-set budgets. The tie is a structural property of
agent workloads, not an artifact of ctx-rm.

## Methodology

Corpus: `~/.claude/projects/-home-akougkas-projects-awoc`, 200 raw
transcripts. Filter cascade: `segs>=40 turns>=8 tool_use>=8 rereads>=1`.
After filtering, **131 / 200 traces** survived (69 filtered, 0 load
errors). The same 131 traces drive every row in every table below.

Policies: `oracle,random,lru,clock,budget,arc,innodb`. Budgets: `4000,
8000, 16000, 32000`. Seed: 0. Reference modes: strict and lenient.
Admission modes: `on` (default 2000-token bypass) and `off`
(`disable_bypass=True`, threshold raised to `sys.maxsize`).

Metrics. `retention` is the new all-future critical-segment retention
(T9, replacing retention@5); `retention@10` is the short-horizon
secondary column. Eviction precision and recall are strict-graph
definitions. Churn is effectively zero across the corpus because L1
never issues recalls; it is kept in the tables for consistency with the
pre-B0 shape. Every cell prints `mean [low, high]` with a 95 % bootstrap
CI over traces (`n=131`, percentile bootstrap, seed 0).

Source runs (bypass=both, both modes, same seed):
`results/b0_awoc_strict.json`, `results/b0_awoc_lenient.json`.

## Headline findings

1. **LRU = ARC = InnoDB at four decimals in every one of the 16 (mode,
   bypass, budget) cells.** This reproduces the A5 "suspicious identity"
   on a corpus that is 1.77× larger and under a harder retention metric.
   The three implementations use different internal state — LRU's
   recency list, ARC's T1/T2/B1/B2 four-list adaptive partition, InnoDB's
   midpoint-insertion LRU — and they still converge to identical
   eviction sequences. See T14 for the mechanism writeup.
2. **Oracle's headroom is robust at working-set budgets and collapses
   at the tie-ceiling budget.** Strict bypass=off: oracle −
   LRU-cluster = 0.164 at 4 k, 0.158 at 8 k, 0.122 at 16 k, 0.070 at
   32 k. Strict bypass=on: 0.134 / 0.066 / 0.019 / 0.002. The 32 k
   strict bypass=on cell prints a 0.002 pp oracle lead, which is the
   "tie ceiling" A2 warned about — at that budget almost nothing is
   evicted, so every policy looks the same.
3. **BudgetAware is last under strict at every working-set budget and
   climbs to second place under lenient at 4 k and 8 k.** This
   reproduces the strict-vs-lenient flip from A5 at larger n and is the
   same signal that BudgetAware's role weights penalize tool_result
   content the strict graph considers critical. The fix is deferred to
   Phase B (B5).
4. **Random is competitive with the LRU cluster on retention and
   sometimes beats it on eviction precision.** Under strict bypass=off
   at 8 k, random retention = 0.680 vs LRU cluster 0.680 (identical
   means, CIs overlap); random precision = 0.684 vs LRU cluster 0.672.
   This is not because random is clever, it is because the re-access
   signal in agent traces is so weak that *nothing* concentrates
   retention on the critical set.
5. **Strict eviction precision numbers survived the graph rewrite.**
   Pre-B0 strict oracle precision at 8 k (retention@5, 74 traces) was
   0.671 [0.623, 0.719]. Post-B0 strict oracle precision at 8 k (same
   budget, 131 traces) is 0.680 [0.649, 0.708]. Within CI overlap, the
   hardened strict graph is not systematically softer or harder — the
   graph rewrite tightened precision per-rule (file_reread 1.000,
   file_discovery 0.951) and the pooled metric stayed flat because
   `exact_quote` still trails on the validation split (0.236).

## Key deltas versus A5

| measurement | pre-B0 (A5) | post-B0 | change |
| --- | :-: | :-: | :-: |
| corpus size | 74 | 131 | +57 traces |
| headline retention metric | retention@5 | all-future retention | redefined |
| oracle retention, strict bypass=off, 8 k | 0.899 [0.874, 0.923] (k=5) | 0.838 [0.797, 0.872] | all-future is harder |
| LRU retention, strict bypass=off, 8 k | 0.851 [0.824, 0.874] (k=5) | 0.680 [0.636, 0.722] | all-future is harder |
| oracle − LRU headroom, 8 k | 0.048 | 0.158 | +0.110 pp |
| oracle eviction precision, strict 8 k | 0.671 [0.623, 0.719] | 0.680 [0.649, 0.708] | flat |
| oracle eviction precision, lenient 8 k | 0.270 [0.232, 0.312] | 0.273 [0.257, 0.288] | flat |
| LRU=ARC=InnoDB tie | 2 cells | 16 cells (all) | structural |
| BudgetAware strict vs lenient flip | present at 8 k | present at 4 k and 8 k | stable |

The retention metric change is the biggest single mover in the table.
All-future retention penalizes every eviction of a later-referenced
segment, not just segments referenced within the next 5 turns, so the
absolute numbers are lower and the oracle-vs-LRU gap is wider. This was
expected; A3 warned that retention@5 was hiding the policy gap by
truncating the horizon. The gap is now visible without the truncation.

## Framing decision

The three-policy tie is not a ctx-rm implementation artifact. Three
independent policies with different internal state converge on identical
eviction sequences in 16 out of 16 cells. This is a statement about the
workload. ARC and InnoDB were engineered to beat LRU by exploiting
frequency and scan resistance. Agent traces overwhelmingly touch each
segment once and then move on, so the signals ARC and InnoDB use to
differentiate themselves from LRU never fire. Oracle's 10 to 16
percentage-point lead proves the headroom exists and is reachable with
future knowledge, so the degeneracy is not "every policy is equally
good" — it is "classical re-access heuristics all collapse to the same
point, far from the ceiling." That is a measurable, previously
unreported property of agent context workloads, and the tool that
surfaces it is the paper contribution.

The T14 investigation will confirm the mechanism. If T14 option (b)
lands and a reactive-ARC variant separates from LRU, the headline
becomes "standard-library ARC silently degrades to LRU on agent
workloads, and here is the fix." If it does not separate, the headline
becomes "even a reactive ARC cannot separate from LRU because the
re-access signal is absent." Both stories are publishable under the
same framing.

## Caveats

- `exact_quote` strict precision on the held-out validation split is
  0.236 (see `docs/eval/phaseB-reference-graph.md`). Roughly three of
  every four edges that rule contributes on unseen traces are false
  positives. The Phase C fix ("require the verbatim window to contain
  the gating identifier token") is not applied in B0 to preserve the
  validation split. The three-policy tie is *eviction-sequence
  identity*, not a precision equality, so it is invariant to
  `exact_quote` noise; the absolute precision numbers in the strict
  tables below should be read with that 17.6 pp tuning-to-validation
  gap in mind.
- Churn is 0.000 in every cell because L1 never issues recalls.
- Random's parity with LRU is a corpus fact, not an experimental error;
  see finding 4.
- ctx-rm-corpus traces are not included. After the filter cascade only
  5 ctx-rm traces survive, which is below the bootstrap floor.

## Tables

### Strict reference mode

#### strict · bypass=off · budget=4000

| policy | n | retention | retention@10 | evict. precision | evict. recall | churn | tokens evicted |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| oracle | 131 | 0.735 [0.691, 0.775] | 0.807 [0.774, 0.836] | 0.686 [0.658, 0.715] | 0.780 [0.745, 0.819] | 0.000 [0.000, 0.000] | 40521 [35838, 45648] |
| random | 131 | 0.568 [0.527, 0.605] | 0.658 [0.625, 0.687] | 0.693 [0.666, 0.718] | 0.728 [0.692, 0.762] | 0.000 [0.000, 0.000] | 40087 [35430, 45149] |
| lru | 131 | 0.571 [0.527, 0.611] | 0.663 [0.627, 0.693] | 0.684 [0.655, 0.713] | 0.775 [0.739, 0.815] | 0.000 [0.000, 0.000] | 40512 [35836, 45647] |
| clock | 131 | 0.573 [0.529, 0.614] | 0.665 [0.629, 0.696] | 0.681 [0.651, 0.710] | 0.764 [0.725, 0.803] | 0.000 [0.000, 0.000] | 40363 [35699, 45528] |
| budget | 131 | 0.542 [0.502, 0.578] | 0.630 [0.598, 0.657] | 0.594 [0.554, 0.635] | 0.576 [0.535, 0.618] | 0.000 [0.000, 0.000] | 39958 [35241, 45108] |
| arc | 131 | 0.571 [0.527, 0.611] | 0.663 [0.627, 0.693] | 0.684 [0.655, 0.713] | 0.775 [0.739, 0.815] | 0.000 [0.000, 0.000] | 40512 [35836, 45647] |
| innodb | 131 | 0.571 [0.527, 0.611] | 0.663 [0.627, 0.693] | 0.684 [0.655, 0.713] | 0.775 [0.739, 0.815] | 0.000 [0.000, 0.000] | 40512 [35836, 45647] |

#### strict · bypass=off · budget=8000

| policy | n | retention | retention@10 | evict. precision | evict. recall | churn | tokens evicted |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| oracle | 131 | 0.838 [0.797, 0.872] | 0.885 [0.855, 0.910] | 0.680 [0.649, 0.708] | 0.626 [0.578, 0.673] | 0.000 [0.000, 0.000] | 36893 [32231, 41988] |
| random | 131 | 0.680 [0.638, 0.719] | 0.742 [0.709, 0.771] | 0.684 [0.655, 0.713] | 0.589 [0.549, 0.626] | 0.000 [0.000, 0.000] | 36998 [32303, 42090] |
| lru | 131 | 0.680 [0.636, 0.722] | 0.749 [0.716, 0.781] | 0.672 [0.640, 0.702] | 0.619 [0.570, 0.667] | 0.000 [0.000, 0.000] | 36901 [32240, 41989] |
| clock | 131 | 0.672 [0.629, 0.714] | 0.741 [0.707, 0.771] | 0.672 [0.641, 0.700] | 0.599 [0.555, 0.645] | 0.000 [0.000, 0.000] | 36897 [32210, 42045] |
| budget | 131 | 0.660 [0.620, 0.699] | 0.721 [0.690, 0.748] | 0.526 [0.483, 0.571] | 0.399 [0.357, 0.441] | 0.000 [0.000, 0.000] | 36710 [32107, 41827] |
| arc | 131 | 0.680 [0.636, 0.722] | 0.749 [0.716, 0.781] | 0.672 [0.640, 0.702] | 0.619 [0.570, 0.667] | 0.000 [0.000, 0.000] | 36901 [32240, 41989] |
| innodb | 131 | 0.680 [0.636, 0.722] | 0.749 [0.716, 0.781] | 0.672 [0.640, 0.702] | 0.619 [0.570, 0.667] | 0.000 [0.000, 0.000] | 36901 [32240, 41989] |

#### strict · bypass=off · budget=16000

| policy | n | retention | retention@10 | evict. precision | evict. recall | churn | tokens evicted |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| oracle | 131 | 0.919 [0.886, 0.945] | 0.950 [0.931, 0.966] | 0.724 [0.691, 0.757] | 0.431 [0.382, 0.480] | 0.000 [0.000, 0.000] | 30886 [26239, 36037] |
| random | 131 | 0.794 [0.760, 0.827] | 0.835 [0.806, 0.862] | 0.722 [0.690, 0.753] | 0.456 [0.410, 0.501] | 0.000 [0.000, 0.000] | 30871 [26228, 35996] |
| lru | 131 | 0.797 [0.759, 0.833] | 0.841 [0.809, 0.869] | 0.714 [0.680, 0.747] | 0.413 [0.367, 0.460] | 0.000 [0.000, 0.000] | 30831 [26198, 35893] |
| clock | 131 | 0.803 [0.766, 0.840] | 0.846 [0.815, 0.874] | 0.698 [0.662, 0.734] | 0.404 [0.358, 0.449] | 0.000 [0.000, 0.000] | 30849 [26199, 35905] |
| budget | 131 | 0.771 [0.733, 0.808] | 0.808 [0.777, 0.837] | 0.576 [0.531, 0.621] | 0.298 [0.261, 0.334] | 0.000 [0.000, 0.000] | 30505 [25931, 35586] |
| arc | 131 | 0.797 [0.759, 0.833] | 0.841 [0.809, 0.869] | 0.714 [0.680, 0.747] | 0.413 [0.367, 0.460] | 0.000 [0.000, 0.000] | 30831 [26198, 35893] |
| innodb | 131 | 0.797 [0.759, 0.833] | 0.841 [0.809, 0.869] | 0.714 [0.680, 0.747] | 0.413 [0.367, 0.460] | 0.000 [0.000, 0.000] | 30831 [26198, 35893] |

#### strict · bypass=off · budget=32000

| policy | n | retention | retention@10 | evict. precision | evict. recall | churn | tokens evicted |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| oracle | 131 | 0.983 [0.968, 0.993] | 0.990 [0.983, 0.996] | 0.810 [0.779, 0.845] | 0.233 [0.186, 0.283] | 0.000 [0.000, 0.000] | 20182 [15808, 25073] |
| random | 131 | 0.917 [0.892, 0.937] | 0.934 [0.914, 0.950] | 0.817 [0.782, 0.850] | 0.234 [0.192, 0.275] | 0.000 [0.000, 0.000] | 19738 [15629, 24862] |
| lru | 131 | 0.913 [0.886, 0.937] | 0.928 [0.905, 0.949] | 0.797 [0.764, 0.832] | 0.211 [0.169, 0.257] | 0.000 [0.000, 0.000] | 19916 [15716, 24837] |
| clock | 131 | 0.919 [0.895, 0.941] | 0.933 [0.910, 0.953] | 0.806 [0.775, 0.840] | 0.208 [0.167, 0.250] | 0.000 [0.000, 0.000] | 20001 [15816, 24951] |
| budget | 131 | 0.898 [0.868, 0.923] | 0.914 [0.888, 0.935] | 0.715 [0.668, 0.762] | 0.211 [0.174, 0.250] | 0.000 [0.000, 0.000] | 20031 [15928, 25080] |
| arc | 131 | 0.913 [0.886, 0.937] | 0.928 [0.905, 0.949] | 0.797 [0.764, 0.832] | 0.211 [0.169, 0.257] | 0.000 [0.000, 0.000] | 19916 [15716, 24837] |
| innodb | 131 | 0.913 [0.886, 0.937] | 0.928 [0.905, 0.949] | 0.797 [0.764, 0.832] | 0.211 [0.169, 0.257] | 0.000 [0.000, 0.000] | 19916 [15716, 24837] |

#### strict · bypass=on · budget=4000

| policy | n | retention | retention@10 | evict. precision | evict. recall | churn | tokens evicted |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| oracle | 131 | 0.793 [0.753, 0.826] | 0.849 [0.823, 0.872] | 0.706 [0.676, 0.738] | 0.709 [0.670, 0.748] | 0.000 [0.000, 0.000] | 14455 [12847, 16105] |
| random | 131 | 0.631 [0.592, 0.667] | 0.711 [0.683, 0.738] | 0.721 [0.694, 0.749] | 0.673 [0.636, 0.707] | 0.000 [0.000, 0.000] | 14212 [12636, 15805] |
| lru | 131 | 0.659 [0.618, 0.696] | 0.735 [0.703, 0.762] | 0.704 [0.674, 0.735] | 0.708 [0.669, 0.747] | 0.000 [0.000, 0.000] | 14451 [12847, 16093] |
| clock | 131 | 0.655 [0.614, 0.691] | 0.733 [0.703, 0.759] | 0.701 [0.671, 0.731] | 0.689 [0.650, 0.729] | 0.000 [0.000, 0.000] | 14169 [12595, 15760] |
| budget | 131 | 0.587 [0.547, 0.622] | 0.667 [0.639, 0.693] | 0.615 [0.575, 0.658] | 0.559 [0.517, 0.603] | 0.000 [0.000, 0.000] | 14138 [12583, 15720] |
| arc | 131 | 0.659 [0.618, 0.696] | 0.735 [0.703, 0.762] | 0.704 [0.674, 0.735] | 0.708 [0.669, 0.747] | 0.000 [0.000, 0.000] | 14451 [12847, 16093] |
| innodb | 131 | 0.659 [0.618, 0.696] | 0.735 [0.703, 0.762] | 0.704 [0.674, 0.735] | 0.708 [0.669, 0.747] | 0.000 [0.000, 0.000] | 14451 [12847, 16093] |

#### strict · bypass=on · budget=8000

| policy | n | retention | retention@10 | evict. precision | evict. recall | churn | tokens evicted |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| oracle | 131 | 0.815 [0.778, 0.848] | 0.864 [0.840, 0.886] | 0.728 [0.692, 0.762] | 0.481 [0.428, 0.534] | 0.000 [0.000, 0.000] | 10755 [9229, 12318] |
| random | 131 | 0.740 [0.703, 0.774] | 0.799 [0.772, 0.824] | 0.741 [0.711, 0.774] | 0.460 [0.418, 0.504] | 0.000 [0.000, 0.000] | 10801 [9311, 12257] |
| lru | 131 | 0.749 [0.711, 0.781] | 0.807 [0.781, 0.830] | 0.726 [0.690, 0.760] | 0.480 [0.428, 0.533] | 0.000 [0.000, 0.000] | 10770 [9232, 12328] |
| clock | 131 | 0.738 [0.702, 0.770] | 0.799 [0.773, 0.823] | 0.704 [0.666, 0.741] | 0.455 [0.404, 0.507] | 0.000 [0.000, 0.000] | 10841 [9283, 12358] |
| budget | 131 | 0.707 [0.669, 0.742] | 0.768 [0.739, 0.794] | 0.597 [0.550, 0.645] | 0.356 [0.313, 0.400] | 0.000 [0.000, 0.000] | 10770 [9205, 12349] |
| arc | 131 | 0.749 [0.711, 0.781] | 0.807 [0.781, 0.830] | 0.726 [0.690, 0.760] | 0.480 [0.428, 0.533] | 0.000 [0.000, 0.000] | 10770 [9232, 12328] |
| innodb | 131 | 0.749 [0.711, 0.781] | 0.807 [0.781, 0.830] | 0.726 [0.690, 0.760] | 0.480 [0.428, 0.533] | 0.000 [0.000, 0.000] | 10770 [9232, 12328] |

#### strict · bypass=on · budget=16000

| policy | n | retention | retention@10 | evict. precision | evict. recall | churn | tokens evicted |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| oracle | 131 | 0.824 [0.789, 0.854] | 0.869 [0.845, 0.889] | 0.850 [0.817, 0.882] | 0.197 [0.155, 0.239] | 0.000 [0.000, 0.000] | 5311 [4091, 6599] |
| random | 131 | 0.802 [0.765, 0.833] | 0.851 [0.827, 0.873] | 0.851 [0.819, 0.882] | 0.186 [0.149, 0.223] | 0.000 [0.000, 0.000] | 5508 [4234, 6843] |
| lru | 131 | 0.805 [0.770, 0.836] | 0.854 [0.831, 0.877] | 0.848 [0.816, 0.881] | 0.194 [0.154, 0.235] | 0.000 [0.000, 0.000] | 5300 [4087, 6571] |
| clock | 131 | 0.802 [0.766, 0.833] | 0.852 [0.827, 0.874] | 0.845 [0.810, 0.879] | 0.193 [0.155, 0.233] | 0.000 [0.000, 0.000] | 5291 [4052, 6622] |
| budget | 131 | 0.788 [0.753, 0.819] | 0.839 [0.813, 0.862] | 0.766 [0.718, 0.812] | 0.175 [0.140, 0.214] | 0.000 [0.000, 0.000] | 5212 [3986, 6520] |
| arc | 131 | 0.805 [0.770, 0.836] | 0.854 [0.831, 0.877] | 0.848 [0.816, 0.881] | 0.194 [0.154, 0.235] | 0.000 [0.000, 0.000] | 5300 [4087, 6571] |
| innodb | 131 | 0.805 [0.770, 0.836] | 0.854 [0.831, 0.877] | 0.848 [0.816, 0.881] | 0.194 [0.154, 0.235] | 0.000 [0.000, 0.000] | 5300 [4087, 6571] |

#### strict · bypass=on · budget=32000

| policy | n | retention | retention@10 | evict. precision | evict. recall | churn | tokens evicted |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| oracle | 131 | 0.824 [0.789, 0.854] | 0.869 [0.845, 0.889] | 0.979 [0.963, 0.992] | 0.024 [0.010, 0.040] | 0.000 [0.000, 0.000] | 1030 [483, 1685] |
| random | 131 | 0.821 [0.788, 0.852] | 0.867 [0.843, 0.887] | 0.972 [0.956, 0.985] | 0.029 [0.014, 0.048] | 0.000 [0.000, 0.000] | 1019 [466, 1671] |
| lru | 131 | 0.822 [0.788, 0.853] | 0.867 [0.844, 0.888] | 0.979 [0.963, 0.992] | 0.024 [0.010, 0.040] | 0.000 [0.000, 0.000] | 1030 [483, 1685] |
| clock | 131 | 0.822 [0.788, 0.852] | 0.867 [0.844, 0.888] | 0.976 [0.958, 0.990] | 0.023 [0.010, 0.038] | 0.000 [0.000, 0.000] | 1013 [472, 1654] |
| budget | 131 | 0.821 [0.787, 0.851] | 0.866 [0.843, 0.887] | 0.963 [0.941, 0.981] | 0.038 [0.018, 0.062] | 0.000 [0.000, 0.000] | 982 [440, 1627] |
| arc | 131 | 0.822 [0.788, 0.853] | 0.867 [0.844, 0.888] | 0.979 [0.963, 0.992] | 0.024 [0.010, 0.040] | 0.000 [0.000, 0.000] | 1030 [483, 1685] |
| innodb | 131 | 0.822 [0.788, 0.853] | 0.867 [0.844, 0.888] | 0.979 [0.963, 0.992] | 0.024 [0.010, 0.040] | 0.000 [0.000, 0.000] | 1030 [483, 1685] |

### Lenient reference mode

#### lenient · bypass=off · budget=4000

| policy | n | retention | retention@10 | evict. precision | evict. recall | churn | tokens evicted |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| oracle | 131 | 0.809 [0.779, 0.834] | 0.839 [0.815, 0.860] | 0.297 [0.283, 0.311] | 0.732 [0.693, 0.773] | 0.000 [0.000, 0.000] | 40499 [35810, 45636] |
| random | 131 | 0.690 [0.662, 0.715] | 0.725 [0.703, 0.744] | 0.300 [0.285, 0.314] | 0.682 [0.644, 0.718] | 0.000 [0.000, 0.000] | 40087 [35430, 45149] |
| lru | 131 | 0.704 [0.674, 0.731] | 0.744 [0.720, 0.765] | 0.296 [0.282, 0.309] | 0.731 [0.692, 0.773] | 0.000 [0.000, 0.000] | 40512 [35836, 45647] |
| clock | 131 | 0.702 [0.673, 0.727] | 0.741 [0.717, 0.761] | 0.292 [0.278, 0.306] | 0.715 [0.675, 0.756] | 0.000 [0.000, 0.000] | 40363 [35699, 45528] |
| budget | 131 | 0.715 [0.688, 0.739] | 0.738 [0.714, 0.760] | 0.191 [0.176, 0.206] | 0.421 [0.383, 0.460] | 0.000 [0.000, 0.000] | 39956 [35239, 45106] |
| arc | 131 | 0.704 [0.674, 0.731] | 0.744 [0.720, 0.765] | 0.296 [0.282, 0.309] | 0.731 [0.692, 0.773] | 0.000 [0.000, 0.000] | 40512 [35836, 45647] |
| innodb | 131 | 0.704 [0.674, 0.731] | 0.744 [0.720, 0.765] | 0.296 [0.282, 0.309] | 0.731 [0.692, 0.773] | 0.000 [0.000, 0.000] | 40512 [35836, 45647] |

#### lenient · bypass=off · budget=8000

| policy | n | retention | retention@10 | evict. precision | evict. recall | churn | tokens evicted |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| oracle | 131 | 0.885 [0.859, 0.906] | 0.907 [0.885, 0.924] | 0.273 [0.257, 0.288] | 0.557 [0.510, 0.603] | 0.000 [0.000, 0.000] | 36884 [32251, 41967] |
| random | 131 | 0.783 [0.759, 0.809] | 0.811 [0.790, 0.833] | 0.288 [0.271, 0.305] | 0.538 [0.499, 0.576] | 0.000 [0.000, 0.000] | 36998 [32303, 42090] |
| lru | 131 | 0.810 [0.784, 0.833] | 0.840 [0.818, 0.861] | 0.270 [0.254, 0.286] | 0.555 [0.507, 0.601] | 0.000 [0.000, 0.000] | 36901 [32240, 41989] |
| clock | 131 | 0.803 [0.776, 0.828] | 0.834 [0.812, 0.854] | 0.261 [0.244, 0.278] | 0.531 [0.487, 0.578] | 0.000 [0.000, 0.000] | 36897 [32210, 42045] |
| budget | 131 | 0.829 [0.804, 0.851] | 0.844 [0.823, 0.863] | 0.145 [0.129, 0.163] | 0.251 [0.219, 0.288] | 0.000 [0.000, 0.000] | 36710 [32107, 41827] |
| arc | 131 | 0.810 [0.784, 0.833] | 0.840 [0.818, 0.861] | 0.270 [0.254, 0.286] | 0.555 [0.507, 0.601] | 0.000 [0.000, 0.000] | 36901 [32240, 41989] |
| innodb | 131 | 0.810 [0.784, 0.833] | 0.840 [0.818, 0.861] | 0.270 [0.254, 0.286] | 0.555 [0.507, 0.601] | 0.000 [0.000, 0.000] | 36901 [32240, 41989] |

#### lenient · bypass=off · budget=16000

| policy | n | retention | retention@10 | evict. precision | evict. recall | churn | tokens evicted |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| oracle | 131 | 0.962 [0.948, 0.976] | 0.972 [0.961, 0.981] | 0.327 [0.286, 0.371] | 0.342 [0.300, 0.386] | 0.000 [0.000, 0.000] | 30768 [26153, 35833] |
| random | 131 | 0.873 [0.853, 0.892] | 0.888 [0.869, 0.904] | 0.359 [0.318, 0.403] | 0.419 [0.373, 0.463] | 0.000 [0.000, 0.000] | 30871 [26228, 35996] |
| lru | 131 | 0.908 [0.888, 0.925] | 0.928 [0.911, 0.941] | 0.326 [0.284, 0.370] | 0.338 [0.296, 0.381] | 0.000 [0.000, 0.000] | 30831 [26198, 35893] |
| clock | 131 | 0.903 [0.882, 0.921] | 0.922 [0.906, 0.935] | 0.311 [0.267, 0.356] | 0.331 [0.289, 0.373] | 0.000 [0.000, 0.000] | 30849 [26199, 35905] |
| budget | 131 | 0.900 [0.881, 0.918] | 0.910 [0.893, 0.924] | 0.203 [0.154, 0.256] | 0.135 [0.115, 0.156] | 0.000 [0.000, 0.000] | 30492 [25905, 35582] |
| arc | 131 | 0.908 [0.888, 0.925] | 0.928 [0.911, 0.941] | 0.326 [0.284, 0.370] | 0.338 [0.296, 0.381] | 0.000 [0.000, 0.000] | 30831 [26198, 35893] |
| innodb | 131 | 0.908 [0.888, 0.925] | 0.928 [0.911, 0.941] | 0.326 [0.284, 0.370] | 0.338 [0.296, 0.381] | 0.000 [0.000, 0.000] | 30831 [26198, 35893] |

#### lenient · bypass=off · budget=32000

| policy | n | retention | retention@10 | evict. precision | evict. recall | churn | tokens evicted |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| oracle | 131 | 1.000 [1.000, 1.000] | 1.000 [1.000, 1.000] | 0.478 [0.412, 0.548] | 0.174 [0.138, 0.215] | 0.000 [0.000, 0.000] | 19896 [15675, 24873] |
| random | 131 | 0.946 [0.930, 0.961] | 0.952 [0.938, 0.964] | 0.533 [0.472, 0.597] | 0.218 [0.178, 0.256] | 0.000 [0.000, 0.000] | 19738 [15629, 24862] |
| lru | 131 | 0.964 [0.951, 0.975] | 0.972 [0.962, 0.981] | 0.476 [0.410, 0.546] | 0.170 [0.134, 0.208] | 0.000 [0.000, 0.000] | 19916 [15716, 24837] |
| clock | 131 | 0.965 [0.952, 0.976] | 0.973 [0.963, 0.982] | 0.476 [0.408, 0.545] | 0.163 [0.129, 0.197] | 0.000 [0.000, 0.000] | 20001 [15816, 24951] |
| budget | 131 | 0.962 [0.950, 0.972] | 0.965 [0.954, 0.974] | 0.410 [0.337, 0.487] | 0.083 [0.066, 0.102] | 0.000 [0.000, 0.000] | 20031 [15928, 25080] |
| arc | 131 | 0.964 [0.951, 0.975] | 0.972 [0.962, 0.981] | 0.476 [0.410, 0.546] | 0.170 [0.134, 0.208] | 0.000 [0.000, 0.000] | 19916 [15716, 24837] |
| innodb | 131 | 0.964 [0.951, 0.975] | 0.972 [0.962, 0.981] | 0.476 [0.410, 0.546] | 0.170 [0.134, 0.208] | 0.000 [0.000, 0.000] | 19916 [15716, 24837] |

#### lenient · bypass=on · budget=4000

| policy | n | retention | retention@10 | evict. precision | evict. recall | churn | tokens evicted |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| oracle | 131 | 0.854 [0.832, 0.874] | 0.866 [0.847, 0.884] | 0.306 [0.292, 0.320] | 0.664 [0.624, 0.705] | 0.000 [0.000, 0.000] | 14445 [12858, 16091] |
| random | 131 | 0.720 [0.695, 0.743] | 0.743 [0.724, 0.763] | 0.321 [0.308, 0.336] | 0.642 [0.603, 0.677] | 0.000 [0.000, 0.000] | 14212 [12636, 15805] |
| lru | 131 | 0.758 [0.733, 0.782] | 0.785 [0.764, 0.804] | 0.304 [0.291, 0.318] | 0.659 [0.618, 0.701] | 0.000 [0.000, 0.000] | 14451 [12847, 16093] |
| clock | 131 | 0.754 [0.729, 0.777] | 0.779 [0.758, 0.799] | 0.299 [0.286, 0.311] | 0.632 [0.593, 0.673] | 0.000 [0.000, 0.000] | 14169 [12595, 15760] |
| budget | 131 | 0.726 [0.702, 0.749] | 0.744 [0.724, 0.764] | 0.201 [0.184, 0.217] | 0.404 [0.366, 0.445] | 0.000 [0.000, 0.000] | 14131 [12581, 15716] |
| arc | 131 | 0.758 [0.733, 0.782] | 0.785 [0.764, 0.804] | 0.304 [0.291, 0.318] | 0.659 [0.618, 0.701] | 0.000 [0.000, 0.000] | 14451 [12847, 16093] |
| innodb | 131 | 0.758 [0.733, 0.782] | 0.785 [0.764, 0.804] | 0.304 [0.291, 0.318] | 0.659 [0.618, 0.701] | 0.000 [0.000, 0.000] | 14451 [12847, 16093] |

#### lenient · bypass=on · budget=8000

| policy | n | retention | retention@10 | evict. precision | evict. recall | churn | tokens evicted |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| oracle | 131 | 0.887 [0.869, 0.904] | 0.891 [0.874, 0.907] | 0.305 [0.271, 0.342] | 0.421 [0.373, 0.473] | 0.000 [0.000, 0.000] | 10755 [9220, 12324] |
| random | 131 | 0.811 [0.790, 0.831] | 0.826 [0.807, 0.843] | 0.336 [0.302, 0.374] | 0.423 [0.380, 0.467] | 0.000 [0.000, 0.000] | 10801 [9311, 12257] |
| lru | 131 | 0.836 [0.814, 0.856] | 0.848 [0.830, 0.865] | 0.304 [0.271, 0.342] | 0.421 [0.373, 0.473] | 0.000 [0.000, 0.000] | 10770 [9232, 12328] |
| clock | 131 | 0.831 [0.809, 0.851] | 0.843 [0.824, 0.860] | 0.283 [0.246, 0.323] | 0.398 [0.348, 0.447] | 0.000 [0.000, 0.000] | 10841 [9283, 12358] |
| budget | 131 | 0.819 [0.799, 0.839] | 0.828 [0.811, 0.845] | 0.216 [0.177, 0.258] | 0.223 [0.192, 0.259] | 0.000 [0.000, 0.000] | 10782 [9203, 12357] |
| arc | 131 | 0.836 [0.814, 0.856] | 0.848 [0.830, 0.865] | 0.304 [0.271, 0.342] | 0.421 [0.373, 0.473] | 0.000 [0.000, 0.000] | 10770 [9232, 12328] |
| innodb | 131 | 0.836 [0.814, 0.856] | 0.848 [0.830, 0.865] | 0.304 [0.271, 0.342] | 0.421 [0.373, 0.473] | 0.000 [0.000, 0.000] | 10770 [9232, 12328] |

#### lenient · bypass=on · budget=16000

| policy | n | retention | retention@10 | evict. precision | evict. recall | churn | tokens evicted |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| oracle | 131 | 0.890 [0.872, 0.906] | 0.893 [0.876, 0.908] | 0.551 [0.481, 0.617] | 0.156 [0.123, 0.191] | 0.000 [0.000, 0.000] | 5299 [4087, 6570] |
| random | 131 | 0.869 [0.850, 0.886] | 0.873 [0.856, 0.888] | 0.593 [0.531, 0.651] | 0.179 [0.144, 0.215] | 0.000 [0.000, 0.000] | 5508 [4234, 6843] |
| lru | 131 | 0.880 [0.861, 0.897] | 0.885 [0.869, 0.900] | 0.551 [0.481, 0.617] | 0.156 [0.123, 0.191] | 0.000 [0.000, 0.000] | 5300 [4087, 6571] |
| clock | 131 | 0.879 [0.860, 0.895] | 0.884 [0.867, 0.898] | 0.543 [0.474, 0.612] | 0.157 [0.124, 0.193] | 0.000 [0.000, 0.000] | 5291 [4052, 6622] |
| budget | 131 | 0.873 [0.853, 0.890] | 0.877 [0.860, 0.892] | 0.496 [0.423, 0.568] | 0.080 [0.064, 0.099] | 0.000 [0.000, 0.000] | 5202 [3986, 6520] |
| arc | 131 | 0.880 [0.861, 0.897] | 0.885 [0.869, 0.900] | 0.551 [0.481, 0.617] | 0.156 [0.123, 0.191] | 0.000 [0.000, 0.000] | 5300 [4087, 6571] |
| innodb | 131 | 0.880 [0.861, 0.897] | 0.885 [0.869, 0.900] | 0.551 [0.481, 0.617] | 0.156 [0.123, 0.191] | 0.000 [0.000, 0.000] | 5300 [4087, 6571] |

#### lenient · bypass=on · budget=32000

| policy | n | retention | retention@10 | evict. precision | evict. recall | churn | tokens evicted |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| oracle | 131 | 0.890 [0.872, 0.906] | 0.893 [0.876, 0.908] | 0.897 [0.849, 0.940] | 0.020 [0.008, 0.034] | 0.000 [0.000, 0.000] | 1030 [483, 1685] |
| random | 131 | 0.888 [0.870, 0.904] | 0.891 [0.875, 0.906] | 0.904 [0.859, 0.945] | 0.025 [0.010, 0.043] | 0.000 [0.000, 0.000] | 1019 [466, 1671] |
| lru | 131 | 0.889 [0.871, 0.905] | 0.892 [0.875, 0.907] | 0.897 [0.849, 0.940] | 0.020 [0.008, 0.034] | 0.000 [0.000, 0.000] | 1030 [483, 1685] |
| clock | 131 | 0.889 [0.871, 0.905] | 0.892 [0.875, 0.907] | 0.897 [0.849, 0.940] | 0.018 [0.007, 0.030] | 0.000 [0.000, 0.000] | 1013 [472, 1654] |
| budget | 131 | 0.888 [0.870, 0.905] | 0.891 [0.875, 0.906] | 0.898 [0.850, 0.943] | 0.013 [0.007, 0.021] | 0.000 [0.000, 0.000] | 982 [440, 1627] |
| arc | 131 | 0.889 [0.871, 0.905] | 0.892 [0.875, 0.907] | 0.897 [0.849, 0.940] | 0.020 [0.008, 0.034] | 0.000 [0.000, 0.000] | 1030 [483, 1685] |
| innodb | 131 | 0.889 [0.871, 0.905] | 0.892 [0.875, 0.907] | 0.897 [0.849, 0.940] | 0.020 [0.008, 0.034] | 0.000 [0.000, 0.000] | 1030 [483, 1685] |

## Next

Task 14 documents the LRU=ARC=InnoDB mechanism and picks one of the
three options (publish the degeneracy, fix the signal, drop the
policies) before any Phase B policy work starts. The T14 outcome is
what turns this document from a baseline table into a paper claim.
