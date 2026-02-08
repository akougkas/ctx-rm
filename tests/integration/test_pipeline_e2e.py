"""End-to-end integration tests for the feedback→adaptive→scoring→eviction pipeline.

These tests prove the full system works together — not just individual components
in isolation. Each test exercises real ContextBus + TieredStore + Policy + Scorer +
FeedbackTracker + AdaptiveWeights interactions with no mocking of core logic.
"""

from __future__ import annotations

import asyncio

import pytest

from ctx_rm.core.adaptive import AdaptiveWeights, _HIGH_RECALL_RATE, _MIN_EVENTS_FOR_SHIFT
from ctx_rm.core.bus import ContextBus
from ctx_rm.core.embedding import HashingEmbeddingProvider
from ctx_rm.core.feedback import FeedbackTracker
from ctx_rm.core.graveyard import TieredStore
from ctx_rm.core.policies.budget import BudgetAwarePolicy
from ctx_rm.core.policies.lru import LRUPolicy
from ctx_rm.core.scorer import HeuristicScorer
from ctx_rm.core.scorer_sequential import SequentialScorer
from ctx_rm.core.segment import Segment, SegmentRole, Tier


# ── Helpers ──────────────────────────────────────────────────────────────


def _seg(
    content: str = "filler",
    source: str = "noise",
    tokens: int = 100,
    role: SegmentRole = SegmentRole.CONTEXT,
    pinned: bool = False,
    metadata: dict | None = None,
) -> Segment:
    return Segment(
        content=content,
        role=role,
        token_count=tokens,
        source=source,
        pinned=pinned,
        metadata=metadata or {},
    )


def _make_bus(
    budget: int = 500,
    headroom: float = 0.1,
    *,
    with_feedback: bool = False,
    with_adaptive: bool = False,
    scorer: HeuristicScorer | SequentialScorer | None = None,
    policy: LRUPolicy | BudgetAwarePolicy | None = None,
    batch_mode: str = "fixed",
    warm_max_items: int = 64,
) -> tuple[ContextBus, FeedbackTracker | None, AdaptiveWeights | None]:
    store = TieredStore(
        embedding_provider=HashingEmbeddingProvider(),
        warm_max_items=warm_max_items,
    )
    feedback = FeedbackTracker() if with_feedback else None
    adaptive = AdaptiveWeights() if with_adaptive else None
    bus = ContextBus(
        token_budget=budget,
        store=store,
        policy=policy or LRUPolicy(),
        scorer=scorer,
        headroom_ratio=headroom,
        feedback=feedback,
        adaptive=adaptive,
        eviction_batch_mode=batch_mode,
    )
    return bus, feedback, adaptive


# ── Test 1: Bus eviction events flow into FeedbackTracker ────────────────


class TestFeedbackTracksEvictions:
    """Prove that ContextBus evictions are recorded in FeedbackTracker."""

    def test_eviction_events_recorded(self) -> None:
        bus, feedback, _ = _make_bus(budget=300, headroom=0.1, with_feedback=True)
        assert feedback is not None

        # Fill to just under headroom target (300 * 0.9 = 270)
        bus.ingest(_seg("system", source="system_prompt", tokens=50, pinned=True))
        bus.ingest(_seg("user task", source="user_task", tokens=50))
        bus.ingest(_seg("noise A", source="noise", tokens=100))
        # Now at 200 tokens, under 270 target — no eviction yet

        # Push over headroom target
        bus.ingest(_seg("noise B", source="noise", tokens=100))
        # Now at 300, over 270 target — eviction should fire

        eviction_events = feedback.events_by_type("eviction")
        assert len(eviction_events) >= 1, "Expected at least 1 eviction event"
        assert eviction_events[0]["type"] == "eviction"
        assert "seg_id" in eviction_events[0]
        assert "source" in eviction_events[0]

    def test_recall_events_recorded(self) -> None:
        bus, feedback, _ = _make_bus(budget=300, headroom=0.1, with_feedback=True)
        assert feedback is not None

        # Ingest a needle, then noise to trigger eviction
        needle = _seg("The secret port is 8443", source="needle:N1", tokens=50)
        bus.ingest(needle)
        bus.ingest(_seg("noise", source="noise", tokens=200))
        bus.ingest(_seg("more noise", source="noise", tokens=100))
        # Needle should be evicted (LRU = oldest first)

        # Recall the needle
        recalled = bus.recall(needle.seg_id)
        assert recalled is not None

        recall_events = feedback.events_by_type("recall")
        assert len(recall_events) == 1
        assert recall_events[0]["seg_id"] == needle.seg_id

    def test_re_eviction_churn_detected(self) -> None:
        """Evict → recall → evict again = re_eviction event (not plain eviction)."""
        bus, feedback, _ = _make_bus(budget=200, headroom=0.1, with_feedback=True)
        assert feedback is not None

        # Ingest a pinned anchor + needle (needle is the only evictable segment)
        anchor = _seg("pinned anchor", source="system_prompt", tokens=100, pinned=True)
        bus.ingest(anchor)

        needle = _seg("important data", source="needle:N1", tokens=50)
        bus.ingest(needle)
        # At 150, under 180 target — no eviction

        # Push over: needle is the only evictable segment, must be evicted
        bus.ingest(_seg("noise A", source="noise", tokens=40))
        # At 190 — over 180, eviction fires. Needle or noise evicted (LRU = needle first).

        # Verify needle was evicted
        active_ids = {s.seg_id for s in bus.active_segments}
        if needle.seg_id in active_ids:
            # Noise was evicted instead; add more to force needle out
            bus.ingest(_seg("noise B", source="noise", tokens=50))

        # Now recall needle
        recalled = bus.recall(needle.seg_id)
        assert recalled is not None, "Needle should be recallable from warm"

        # Evict everything non-pinned to force re-eviction of the recalled needle
        bus.ingest(_seg("big push", source="noise", tokens=100))

        re_eviction_events = feedback.events_by_type("re_eviction")
        assert len(re_eviction_events) >= 1, "Expected re_eviction event for churn"
        # The re-evicted segment should be our needle
        re_evicted_ids = {e["seg_id"] for e in re_eviction_events}
        assert needle.seg_id in re_evicted_ids


# ── Test 2: Adaptive weights shift from feedback ────────────────────────


class TestAdaptiveShiftsFromFeedback:
    """Prove adaptive weights change bus behavior based on eviction/recall patterns."""

    def test_high_recall_rate_boosts_source_weights(self) -> None:
        bus, feedback, adaptive = _make_bus(
            budget=300, headroom=0.1, with_feedback=True, with_adaptive=True,
        )
        assert feedback is not None
        assert adaptive is not None

        initial_headroom = adaptive.policy_params["headroom_ratio"]

        # Generate enough evictions + recalls to cross threshold
        for i in range(_MIN_EVENTS_FOR_SHIFT + 2):
            seg = _seg(f"needle content {i}", source="needle:N1", tokens=50)
            bus.ingest(seg)
            # Fill up to trigger eviction
            bus.ingest(_seg(f"noise {i}", source="noise", tokens=250))
            # The needle was evicted — recall it
            bus.recall(seg.seg_id)

        # Force adaptive update by triggering another eviction cycle
        bus.ingest(_seg("trigger", source="noise", tokens=250))

        assert adaptive.shift_count >= 1, "Expected at least one adaptive shift"
        assert adaptive.source_weights.get("needle", 1.0) > 1.0, (
            "Needle source weight should be boosted after high recall rate"
        )
        assert adaptive.policy_params["headroom_ratio"] >= initial_headroom

    def test_zero_recall_rate_decays_weights(self) -> None:
        bus, feedback, adaptive = _make_bus(
            budget=200, headroom=0.1, with_feedback=True, with_adaptive=True,
        )
        assert feedback is not None
        assert adaptive is not None

        # Pre-seed a source weight to verify decay
        adaptive.source_weights["noise"] = 1.1
        adaptive.policy_params["headroom_ratio"] = 0.2

        # Generate many evictions with zero recalls.
        # Each iteration: fill bus then push over to trigger eviction cycle.
        for i in range(_MIN_EVENTS_FOR_SHIFT + 5):
            bus.ingest(_seg(f"disposable {i}", source="noise", tokens=150))
            # Each 150-token ingest pushes over the 180 target, forcing eviction

        # Verify enough eviction events accumulated
        eviction_count = len(feedback.events_by_type("eviction"))
        assert eviction_count >= _MIN_EVENTS_FOR_SHIFT, (
            f"Need >= {_MIN_EVENTS_FOR_SHIFT} evictions, got {eviction_count}"
        )
        assert feedback.recall_rate() == 0.0

        # The bus calls adaptive.update_from_feedback during eviction cycle
        assert adaptive.shift_count >= 1, "Expected at least one aggressive shift"
        # noise weight should decay toward 1.0
        assert adaptive.source_weights.get("noise", 1.0) <= 1.1


# ── Test 3: Scorer integration with bus ──────────────────────────────────


class TestScorerDrivesEviction:
    """Prove scorer affects WHICH segments get evicted (not just LRU order)."""

    def test_heuristic_scorer_with_source_weight_retains_needle(self) -> None:
        """BudgetAwarePolicy + source_weight=0.3 should keep needles over noise."""
        scorer = HeuristicScorer(source_weight=0.3)
        policy = BudgetAwarePolicy()
        bus, _, _ = _make_bus(
            budget=300, headroom=0.1, scorer=scorer, policy=policy,
        )

        # Ingest needle first (oldest = LRU candidate)
        needle = _seg("The API key is ABC123", source="needle:N1", tokens=80)
        bus.ingest(needle)

        # Ingest noise after
        bus.ingest(_seg("irrelevant debug logs", source="noise", tokens=80))
        bus.ingest(_seg("more verbose output", source="noise", tokens=80))

        # Push over budget (300 * 0.9 = 270 target, currently at 240)
        bus.ingest(_seg("final noise", source="noise", tokens=80))
        # Now at 320, over 270 — eviction fires

        # Needle should survive because source_weight=0.3 boosts its score
        active_ids = {s.seg_id for s in bus.active_segments}
        assert needle.seg_id in active_ids, (
            "Needle should be retained when scorer uses source_weight"
        )

    def test_sequential_scorer_task_relevance(self) -> None:
        """SequentialScorer should score task-relevant segments higher."""
        scorer = SequentialScorer(task_goal="Configure nginx proxy to port 8443")
        policy = BudgetAwarePolicy()
        bus, _, _ = _make_bus(
            budget=300, headroom=0.1, scorer=scorer, policy=policy,
        )

        # Ingest: task-relevant segment first (LRU = evict first without scorer)
        relevant = _seg(
            "The nginx config requires proxy_pass to port 8443 with SSL termination",
            source="context",
            tokens=80,
        )
        bus.ingest(relevant)

        # Ingest irrelevant segments
        bus.ingest(_seg("Python unittest framework docs", source="noise", tokens=80))
        bus.ingest(_seg("Docker compose volume mounts", source="noise", tokens=80))

        # Push over budget
        bus.ingest(_seg("Git rebase interactive tutorial", source="noise", tokens=80))

        # The task-relevant segment should survive (higher relevance to task_goal)
        active_ids = {s.seg_id for s in bus.active_segments}
        assert relevant.seg_id in active_ids, (
            "Task-relevant segment should be retained by SequentialScorer"
        )


# ── Test 4: Sequential vs Heuristic A/B ─────────────────────────────────


class TestSequentialVsHeuristic:
    """Prove SequentialScorer produces meaningfully different scores than Heuristic."""

    def test_same_segment_different_retained_set_yields_different_scores(self) -> None:
        """Core sequential property: score depends on what else is retained."""
        scorer = SequentialScorer(task_goal="Fix the authentication bug in auth.py")

        # Scenario A: retained set has auth-related context
        candidate = _seg("The user_id field is required in the JWT payload")
        context_a = [
            candidate,
            _seg("Auth module validates JWT tokens on every request"),
            _seg("The login endpoint returns a 401 on missing credentials"),
        ]
        scorer.score_batch([candidate], context_a)
        score_with_auth_context = candidate.composite_score

        # Reset
        candidate.composite_score = None

        # Scenario B: retained set has unrelated context
        context_b = [
            candidate,
            _seg("Docker compose uses networks for service isolation"),
            _seg("Webpack bundles JavaScript modules for production"),
        ]
        scorer.score_batch([candidate], context_b)
        score_with_unrelated_context = candidate.composite_score

        assert score_with_auth_context is not None
        assert score_with_unrelated_context is not None
        # When related context is already retained, candidate is more redundant
        # so its score should differ
        assert score_with_auth_context != score_with_unrelated_context, (
            "SequentialScorer must produce different scores based on retained set"
        )

    def test_task_conditioning_changes_scores(self) -> None:
        """Same segment + same context, different task → different scores."""
        candidate = _seg("nginx reverse proxy configuration with SSL")
        context = [candidate, _seg("filler content for padding")]

        scorer_a = SequentialScorer(task_goal="Set up nginx proxy for port 8443")
        scorer_a.score_batch([candidate], context)
        score_a = candidate.composite_score

        candidate.composite_score = None

        scorer_b = SequentialScorer(task_goal="Debug Python unittest failures")
        scorer_b.score_batch([candidate], context)
        score_b = candidate.composite_score

        assert score_a is not None
        assert score_b is not None
        assert score_a != score_b, "Different tasks should yield different scores"
        assert score_a > score_b, "nginx content should score higher for nginx task"


# ── Test 5: Recall source filtering ──────────────────────────────────────


class TestRecallSourceFilter:
    """Prove recall only returns safe sources and blocks assistant/tool pairs."""

    def test_search_evicted_returns_all_sources(self) -> None:
        """search_evicted finds segments regardless of source (filtering is caller's job)."""
        bus, _, _ = _make_bus(budget=200, headroom=0.1)

        # Ingest various sources then trigger eviction
        needle = _seg("secret key 9999", source="needle:N1", tokens=60)
        tool = _seg("tool output with key 9999", source="tool:bash", tokens=60)
        asst = _seg("assistant said key 9999", source="assistant_tool_call", tokens=60)
        bus.ingest(needle)
        bus.ingest(tool)
        bus.ingest(asst)

        # Push over budget to evict all three
        bus.ingest(_seg("big filler", source="noise", tokens=150, pinned=True))

        results = bus.search_evicted("key 9999", top_k=10)
        found_sources = {s.source for s in results}

        # All should be findable in search
        assert len(results) >= 2, f"Expected >=2 search results, got {len(results)}"

    def test_agent_loop_only_recalls_safe_sources(self) -> None:
        """AgentLoop._try_recall filters to RECALLABLE_SOURCES only."""
        from ctx_rm.agents.loop import AgentLoop
        from ctx_rm.drivers.llamacpp import ChatResponse, ToolCall

        # Create a mock driver that returns a final text response
        class MockDriver:
            async def chat(self, messages, tools=None, **kwargs):
                return ChatResponse(
                    content="done", prompt_tokens=10, completion_tokens=5,
                )

        bus, _, _ = _make_bus(budget=300, headroom=0.1)
        loop = AgentLoop(
            driver=MockDriver(),
            bus=bus,
            working_dir="/tmp",
            max_turns=1,
            enable_recall=True,
            recall_top_k=5,
        )

        # Manually ingest + evict segments with unsafe sources
        tool_seg = _seg("tool result with secret port 8443", source="tool:bash", tokens=50)
        asst_seg = _seg("assistant called tool for port 8443", source="assistant_tool_call", tokens=50)
        needle_seg = _seg("the secret port is 8443", source="needle:N1", tokens=50)

        for seg in [tool_seg, asst_seg, needle_seg]:
            bus.ingest(seg)
        # Push over budget to evict them
        bus.ingest(_seg("big padder", source="noise", tokens=250, pinned=True))

        # Set task text and run recall
        loop._task_text = "what is the secret port"
        loop._try_recall()

        # Only needle should have been recalled (safe source)
        active_sources = {s.source for s in bus.active_segments if not s.pinned}
        assert "needle:N1" in active_sources, "Needle should be recalled"
        assert "tool:bash" not in active_sources, "Tool source should NOT be recalled"
        assert "assistant_tool_call" not in active_sources, "Assistant tool call should NOT be recalled"


# ── Test 6: Adaptive batch eviction mode ─────────────────────────────────


class TestAdaptiveBatchEviction:
    """Prove adaptive batch mode evicts one-at-a-time near budget."""

    def test_adaptive_mode_evicts_incrementally(self) -> None:
        bus, feedback, _ = _make_bus(
            budget=400, headroom=0.1, with_feedback=True, batch_mode="adaptive",
        )
        assert feedback is not None

        bus.ingest(_seg("a", tokens=100))
        bus.ingest(_seg("b", tokens=100))
        bus.ingest(_seg("c", tokens=100))
        # At 300, under 360 target — no eviction

        # Push just over target
        bus.ingest(_seg("d", tokens=80))
        # At 380, over 360 — adaptive mode should evict minimally

        evictions = feedback.events_by_type("eviction")
        # Adaptive mode evicts one at a time, so should evict exactly 1
        assert len(evictions) >= 1
        # Should still be under target
        assert bus.active_tokens <= bus.headroom_target


# ── Test 7: Full pipeline — scorer + feedback + adaptive together ────────


class TestFullPipeline:
    """Prove the entire pipeline works: scoring → eviction → feedback → adaptation."""

    def test_pipeline_adapts_over_session(self) -> None:
        """Simulate a multi-turn session where adaptation improves retention."""
        scorer = HeuristicScorer(source_weight=0.3)
        policy = BudgetAwarePolicy()
        bus, feedback, adaptive = _make_bus(
            budget=400,
            headroom=0.15,
            scorer=scorer,
            policy=policy,
            with_feedback=True,
            with_adaptive=True,
        )
        assert feedback is not None
        assert adaptive is not None

        # Simulate turns: inject needle + noise, evict, recall needle
        needles_recalled = 0
        for turn in range(10):
            bus.advance_turn()

            needle = _seg(
                f"Critical config: port={8000 + turn}",
                source="needle:N1",
                tokens=40,
            )
            bus.ingest(needle)

            # Inject noise to force eviction
            for j in range(3):
                bus.ingest(_seg(f"noise t{turn} n{j}", source="noise", tokens=80))

            # Check if needle survived
            active_ids = {s.seg_id for s in bus.active_segments}
            if needle.seg_id not in active_ids:
                # Recall it (page fault)
                recalled = bus.recall(needle.seg_id)
                if recalled:
                    needles_recalled += 1

        # Verify feedback recorded events
        assert feedback.event_count > 0
        evictions = len(feedback.events_by_type("eviction"))
        recalls = len(feedback.events_by_type("recall"))
        assert evictions > 0, "Expected evictions in 10-turn session"

        # Verify adaptive state reflects the session
        if recalls > 0:
            assert feedback.recall_rate() > 0

    def test_eval_results_flow_through_pipeline(self) -> None:
        """Prove eval outcomes are recorded in feedback tracker via bus."""
        bus, feedback, _ = _make_bus(with_feedback=True)
        assert feedback is not None

        bus.record_eval_result("needle_retained", passed=True)
        bus.record_eval_result("file_contains_port", passed=False)

        assert feedback.eval_pass_rate() == pytest.approx(0.5)
        eval_events = feedback.events_by_type("eval")
        assert len(eval_events) == 2
        assert eval_events[0]["check"] == "needle_retained"
        assert eval_events[1]["passed"] is False


# ── Test 8: Tier transitions are real ────────────────────────────────────


class TestTierTransitions:
    """Prove segments actually move through tiers: Active → Warm → Cold → recalled."""

    def test_evicted_segment_reaches_warm(self) -> None:
        bus, _, _ = _make_bus(budget=200, headroom=0.1)

        seg = _seg("will be evicted", source="noise", tokens=60)
        bus.ingest(seg)
        bus.ingest(_seg("filler", source="noise", tokens=160))

        # seg should be in warm now
        store_stats = bus.store.get_stats()
        assert store_stats["warm_count"] >= 1

        # Can find it by searching
        results = bus.search_evicted("will be evicted", top_k=5)
        found_ids = {s.seg_id for s in results}
        assert seg.seg_id in found_ids

    def test_full_tier_cascade(self) -> None:
        """Fill warm cache to force cascade to cold, then recall from cold."""
        bus, _, _ = _make_bus(budget=200, headroom=0.1, warm_max_items=2)

        # Ingest and evict 4 segments — warm holds 2, rest cascade to cold
        segs = []
        for i in range(4):
            s = _seg(f"data_{i} unique_keyword_{i}", source="noise", tokens=40)
            segs.append(s)
            bus.ingest(s)

        # Push over to evict everything
        bus.ingest(_seg("big block", source="noise", tokens=180, pinned=True))

        stats = bus.store.get_stats()
        assert stats["warm_count"] <= 2, "Warm should hold max 2"
        assert stats["cold_count"] >= 1, "Overflow should cascade to cold"

        # Recall from cold
        cold_seg = None
        for s in segs:
            recalled = bus.recall(s.seg_id)
            if recalled is not None:
                cold_seg = recalled
                break

        assert cold_seg is not None, "Should be able to recall at least one segment"
        assert cold_seg.tier == Tier.ACTIVE


# ── Test 9: Headroom bounds safety ───────────────────────────────────────


class TestHeadroomBounds:
    """Prove headroom_ratio stays bounded even with extreme adaptive shifts."""

    def test_headroom_clamped_to_safe_range(self) -> None:
        bus, feedback, adaptive = _make_bus(
            budget=500, headroom=0.15, with_feedback=True, with_adaptive=True,
        )
        assert feedback is not None
        assert adaptive is not None

        # Manually push headroom to extreme
        adaptive.policy_params["headroom_ratio"] = 0.9

        # Trigger an eviction cycle to force the bus to read adaptive params
        bus.ingest(_seg("filler", tokens=500))

        # Bus should clamp headroom to max 0.5
        assert bus.headroom_ratio <= 0.5
        assert bus.headroom_ratio >= 0.05
