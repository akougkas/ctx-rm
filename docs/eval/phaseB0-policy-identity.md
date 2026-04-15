# Phase B0 policy identity: why LRU, ARC, and InnoDB tie on agent traces

## Mechanism

I reproduced the identity on three allowed tuning-split traces, all outside
`docs/eval/phaseB0-burn-traces.txt`, with `disable_bypass=True`, strict
reference mode, and an 8k token budget. The results are bit-identical at the
eviction-sequence level and show no recalls anywhere in the run:

- `tuning[0]`: 71 segments, 56 evictions, `lru == arc`, `lru == innodb`,
  `n_recalls = 0` for all three policies.
- `tuning[1]`: 59 segments, 44 evictions, `lru == arc`, `lru == innodb`,
  `n_recalls = 0` for all three policies.
- `tuning[5]`: 41 segments, 26 evictions, `lru == arc`, `lru == innodb`,
  `n_recalls = 0` for all three policies.

The runner behavior explains why the tie is structural. Normalization gives
each trace segment a deterministic ID that is unique within the trace because
`seg_id` is derived from `(trace_id, turn_index, event_index, kind, content)`
and `event_index` is strictly monotonic across the stream
(`src/ctx_rm/eval/trace/normalize.py:51-65`,
`src/ctx_rm/eval/trace/schema.py:66-72`). Replay then walks that normalized
stream exactly once, in order, and ingests each segment once:

```python
for ts in config.trace.segments:
    if not ts.content and ts.token_count == 0:
        continue

    if ts.turn_index != current_turn:
        if current_turn >= 0:
            _snapshot(current_turn)
        current_turn = ts.turn_index
        bus.advance_turn(turn_number=current_turn)
        if isinstance(policy, OraclePolicy):
            policy.set_current_turn(current_turn)

    seg = _trace_to_segment(ts, pin_system=config.pin_system)
    bus.ingest(seg)
    ingested += 1
```

That is `src/ctx_rm/eval/l1_mechanism/runner.py:175-190`. There is no second
pass, no re-ingest of an evicted segment, and no replay path that touches a
cached segment after it enters Active. The only runner action on a segment is
`bus.ingest`. Inside the bus, `ingest` calls `policy.on_ingest`
(`src/ctx_rm/core/bus.py:151-219`, especially `191-192`). Policy
`on_access` only fires on `recall` or `touch_segment`
(`src/ctx_rm/core/bus.py:301-320`, `339-352`). Because L1 replay never calls
either path and the reproduced runs recorded `n_recalls = 0`, ARC and InnoDB
never receive the re-access signal that would separate them from LRU.

ARC’s adaptive state never moves off its default. The policy initializes
`self._p = 0.0` (`src/ctx_rm/core/policies/arc.py:47-48`). The only code that
increases `p` is the B1 ghost-hit branch in `on_ingest`
(`src/ctx_rm/core/policies/arc.py:61-71`). The only code that decreases `p`
is the B2 ghost-hit branch in `on_ingest`
(`src/ctx_rm/core/policies/arc.py:73-82`). Both branches require the policy to
see the same `seg_id` again after it was evicted into a ghost list. Under L1
replay that never happens: segments are ingested once, seg_ids are unique, and
replay never re-ingests an evicted segment. As a result, every new segment
falls through to “Case 4” and enters T1
(`src/ctx_rm/core/policies/arc.py:88-89`). Nothing promotes from T1 to T2
because that only happens in `on_access`
(`src/ctx_rm/core/policies/arc.py:91-101`). When ARC selects victims, it checks
whether `t1_tokens > p` and, with `p` stuck at `0.0`, drains T1 before T2
(`src/ctx_rm/core/policies/arc.py:138-149`). In this workload T2 stays empty,
so ARC reduces to oldest-first eviction out of T1, which matches LRU’s
oldest-`last_accessed` ordering (`src/ctx_rm/core/policies/lru.py:21-26`).

InnoDB collapses for the same reason. New segments always enter the old
sublist in ingestion order (`src/ctx_rm/core/policies/innodb.py:58-69`). The
only path that promotes a segment from old to new is `on_access`
(`src/ctx_rm/core/policies/innodb.py:71-84`). Since L1 replay never calls
`on_access`, `_new` stays empty and `_old` becomes a pure arrival-order queue.
Victim selection prefers the old sublist first and iterates it oldest-first
(`src/ctx_rm/core/policies/innodb.py:114-123`). That is the same behavior as
LRU on a trace where no segment is ever touched again after ingestion. The
observed bit-identical eviction sequences are exactly what the code predicts.

This matters because it rules out a ctx-rm artifact explanation. The tie does
not come from a scoring bug, a reference-graph quirk, or admission bypass. The
reproduction above disables bypass, uses three different traces, and still
gets the same sequence because agent-trace replay supplies a one-shot stream
with no honest re-access events for ARC or InnoDB to exploit.

## Decision

Selected path: **(b) fix the signal, minimally and honestly.** The change here
is narrow by design: during replay, if a `tool_result` body reappears with an
identical content fingerprint after the earlier copy was evicted, the runner
tags the new segment with the prior evicted segment ID. ARC then consumes that
tag as a ghost-hit alias and promotes the returning content into T2 under the
new segment ID; InnoDB treats the returning content as a re-access and inserts
it directly into the protected `new` sublist. This uses only information
available at replay time, from the prefix of the trace already seen, so it does
not leak oracle knowledge. On a crafted regression trace with repeated
evicted-content reappearance, LRU still evicts the returning block once it
becomes old, while ARC and InnoDB keep it alive longer. That said, this does
change the semantics of the ARC and InnoDB rows in the published baseline, so
the T13 tables are stale until they are rerun under the new signal. That rerun
is a separate pause point because it republishes benchmark numbers.
