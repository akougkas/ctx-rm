"""ctx-rm evaluation suite.

Three-tier methodology for measuring eviction policy quality:

- `l1_mechanism`: offline, deterministic replay of recorded agent traces
  against ContextBus. No LLM. Reports eviction precision/recall, critical
  segment retention, and churn against oracle and random controls.
- `l2_replay`: transcript replay with counterfactual prompt-divergence
  metrics against the recorded prefix.
- `l3_live`: narrow live end-to-end runs through AgentLoop and ContextBus.

See docs/eval/README.md for the methodology writeup.
"""
