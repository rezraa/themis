# Copyright (c) 2026 Reza Malik. Licensed under the Apache License, Version 2.0.
"""Themis S3 gate — plan_test_strategy retrofit onto the hydrate seams.

Proves the S3 north star at the loader/testbed level (no live DB, no re-seed):

* the tool retrieves through kb.hydrate / kb.hydrate_patterns, reasoning over each
  matched node's OWN fields — real nested complexity {setup,maintenance,execution},
  compatible_frameworks (so top-level ``frameworks`` is no longer always empty),
  applies_when/avoid_when/trade_offs (S5 dropped the separate matched_rules provenance
  block — the strategy's own why-fields ARE the single source);
* agent-pattern detection surfaces the rich agent_patterns.json corpus
  (test_approach / example_test_case / metrics / severity / adapters);
* the hardcoded agent-signal/agent-pattern island is deleted at zero references;
* the fail-closed envelope abstains to honest empty + unmatched_signals, never a husk.

Directive 8: the signal ids come from the LIVE get_signal_index accessor's OWN
output, never a hand-built fixture. The RED baseline (measured before the retrofit):
feeding these accessor ids to the pre-S3 tool returned recommended_strategies=[],
frameworks=[] and no agent_patterns block, because the tool matched prose against the
decision-rules table and never the accessor's own 226-signal vocabulary.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from themis.tools.get_signal_index import get_signal_index
from themis.tools.plan_test_strategy import plan_test_strategy
from themis.tools._shared import get_knowledge


@pytest.fixture(scope="module")
def accessor_ids() -> dict:
    """Signal ids drawn from the LIVE accessor: two strategy signals that map to a
    rule-recommended strategy (``unit_isolation``) + one agent-pattern signal."""
    idx = get_signal_index()
    strat = [e["signal_id"] for e in idx["strategy_signals"]
             if "unit_isolation" in e["strategy_ids"]][:2]
    pat = idx["pattern_signals"][0]
    assert len(strat) == 2, "corpus should expose >=2 signals for unit_isolation"
    return {"strategy": strat, "pattern": pat["signal_id"], "pattern_ids": pat["pattern_ids"]}


class TestOwnFieldReasoning:
    """RED->GREEN: accessor ids yield a strategy with its OWN fields + real frameworks."""

    def test_recommended_strategy_carries_real_complexity_and_frameworks(self, accessor_ids):
        res = plan_test_strategy(
            system_description="a pure function under test",
            structural_signals=accessor_ids["strategy"] + [accessor_ids["pattern"]],
        )
        assert res["retrieval_state"] in ("hit", "low_confidence")
        rec = res["recommended_strategies"]
        assert rec, "recommended_strategies must be non-empty for accessor-matched ids"
        ui = next(r for r in rec if r["strategy_id"] == "unit_isolation")
        # Real nested complexity — not the phantom flat setup_complexity default.
        assert set(ui["complexity"]) == {"setup", "maintenance", "execution"}
        assert ui["complexity"] == {"setup": "low", "maintenance": "low", "execution": "fast"}
        # Real compatible_frameworks — not the phantom ``frameworks`` key.
        assert "pytest" in ui["compatible_frameworks"]
        # Own-field reasoning surfaced.
        assert ui["applies_when"] and ui["avoid_when"] and ui["trade_offs"]

    def test_top_level_frameworks_no_longer_empty(self, accessor_ids):
        res = plan_test_strategy(
            system_description="a pure function under test",
            structural_signals=accessor_ids["strategy"],
        )
        assert res["frameworks"], "top-level frameworks was always [] before the field fix"
        assert "pytest" in res["frameworks"]

    def test_no_matched_rules_block(self, accessor_ids):
        """S5 dropped the decision-rule provenance block; the strategy's own
        applies_when/avoid_when/trade_offs are the single why-source."""
        res = plan_test_strategy(
            system_description="a pure function under test",
            structural_signals=accessor_ids["strategy"],
        )
        assert "matched_rules" not in res


class TestAgentPatternCorpus:
    """Agent-pattern detection flows through the real corpus, not the deleted island."""

    def test_agent_patterns_carry_rich_corpus_fields(self, accessor_ids):
        res = plan_test_strategy(
            system_description="an agent that chains sub-agents",
            structural_signals=accessor_ids["strategy"] + [accessor_ids["pattern"]],
        )
        assert res["agent_pattern_state"] in ("hit", "low_confidence")
        assert "agent_patterns" in res and res["agent_patterns"]
        target = accessor_ids["pattern_ids"][0]
        block = next(p for p in res["agent_patterns"] if p["pattern_id"] == target)
        # The rich fields the hardcoded island never carried.
        assert block["test_approach"]
        assert block["metrics"]
        assert block["severity"]
        assert block["adapters"]

    def test_island_deleted_at_zero_references(self):
        import sys
        # The package re-exports the function under the same dotted name, so resolve
        # the actual module object via sys.modules rather than attribute lookup.
        mod = sys.modules[plan_test_strategy.__module__]
        assert not hasattr(mod, "_AGENT_SIGNALS")
        assert not hasattr(mod, "_AGENT_PATTERNS")
        # No file under src/themis defines the island symbols any more.
        src_root = Path(mod.__file__).resolve().parents[1]
        hits = [
            str(p) for p in src_root.rglob("*.py")
            if "_AGENT_SIGNALS" in p.read_text(encoding="utf-8")
            or "_AGENT_PATTERNS" in p.read_text(encoding="utf-8")
        ]
        assert hits == [], f"island symbols still referenced in: {hits}"

    def test_tool_no_longer_calls_the_substring_matcher(self):
        import sys
        mod = sys.modules[plan_test_strategy.__module__]
        assert "match_structural_signals(" not in inspect.getsource(mod)


class TestFailClosed:
    """NO_MATCH/DANGLING abstain to honest empty + unmatched_signals, never a husk."""

    def test_unrecognised_id_abstains_on_both_legs(self):
        res = plan_test_strategy(
            system_description="anything",
            structural_signals=["sig-deadbeef0000"],
        )
        assert res["retrieval_state"] == "no_match"
        assert res["agent_pattern_state"] == "no_match"
        assert res["recommended_strategies"] == []
        assert "matched_rules" not in res
        assert res["frameworks"] == []
        assert res["alternatives"] == []
        assert "agent_patterns" not in res
        assert res["unmatched_signals"] == ["sig-deadbeef0000"]

    def test_recognised_ids_are_not_reported_unmatched(self, accessor_ids):
        # Each id is recognised by exactly one view, so NEITHER is unmatched overall.
        res = plan_test_strategy(
            system_description="mixed",
            structural_signals=accessor_ids["strategy"] + [accessor_ids["pattern"]],
        )
        assert res["unmatched_signals"] == []


class TestMcpBoundaryContractPreserved:
    """The two required params stay honestly required (test_tool_hardening contract)."""

    def test_missing_structural_signals_raises(self):
        with pytest.raises(TypeError, match="structural_signals"):
            plan_test_strategy(system_description="x")

    def test_missing_system_description_raises(self):
        with pytest.raises(TypeError):
            plan_test_strategy(structural_signals=["sig-1"])

    def test_lone_stray_string_maps_to_system_description(self):
        res = plan_test_strategy(structural_signals=["sig-1"], target="A system")
        assert isinstance(res, dict)

    def test_unknown_kwarg_raises(self):
        with pytest.raises(TypeError):
            plan_test_strategy(
                system_description="x",
                structural_signals=["sig-1"],
                bogus={"not": "a string"},
            )

    def test_wrong_type_constraints_does_not_crash(self):
        res = plan_test_strategy(
            system_description="x",
            structural_signals=["sig-1"],
            constraints="production",
        )
        assert isinstance(res, dict)
