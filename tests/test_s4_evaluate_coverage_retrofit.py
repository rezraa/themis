# Copyright (c) 2026 Reza Malik. Licensed under the Apache License, Version 2.0.
"""Themis S4 gate — evaluate_coverage retrofit onto the hydrate seams.

Proves the S4 north star at the loader/testbed level (no live DB, no re-seed):

* coverage gaps are measured against the REACHABLE corpus — the strategies and
  agent patterns actually recommended for the system's OWN signals, retrieved
  through kb.hydrate / kb.hydrate_patterns and the four-state fail-closed envelope
  — so ``missing_strategies`` names real corpus strategy nodes (was []) and
  ``risk_areas`` names real corpus nodes (was the hardcoded category rubric only);
* ``_DEFAULT_CATEGORIES`` is demoted from content-monopoly to scoring weights
  (recommended_min, priority) — the corpus ``category`` supplies the content, so a
  corpus category the rubric never held (e.g. "unit") now appears in
  ``coverage_by_category`` carrying its recommended real strategies;
* the tool no longer calls the legacy substring matcher (S5 dependency);
* the envelope abstains to honest empty on no match, never a fabricated corpus node.

Directive 8: the signal ids come from the LIVE get_signal_index accessor's OWN
output, never a hand-built fixture. The RED baseline (measured before the retrofit):
feeding these accessor ids to the pre-S4 tool returned missing_strategies=[] and
risk_areas naming only the 9 hardcoded rubric categories, because it matched the ids
against the 45 decision_rules signals (never the corpus's own vocabulary) and read
the phantom ``recommended_pattern`` key the loader never sets.
"""

from __future__ import annotations

import inspect
import sys

import pytest

from themis.tools.evaluate_coverage import evaluate_coverage, _DEFAULT_CATEGORIES
from themis.tools.get_signal_index import get_signal_index
from themis.tools._shared import get_knowledge


@pytest.fixture(scope="module")
def accessor_ids() -> dict:
    """Signal ids drawn from the LIVE accessor: strategy signals that map to a real
    corpus strategy (``unit_isolation``) + one agent-pattern signal."""
    idx = get_signal_index()
    strat = [e["signal_id"] for e in idx["strategy_signals"]
             if "unit_isolation" in e["strategy_ids"]][:2]
    pat = idx["pattern_signals"][0]
    assert len(strat) == 2, "corpus should expose >=2 signals for unit_isolation"
    return {"strategy": strat, "pattern": pat["signal_id"], "pattern_ids": pat["pattern_ids"]}


# A single functional test that covers NONE of the recommended corpus strategies,
# so the reachable-corpus gap is real and observable.
_TESTS = [{"name": "test_login", "category": "functional", "what_it_tests": "login happy path"}]
_SYS = "A pure function under test in a multi-agent LLM system with tool use"


class TestReachableCorpusGaps:
    """RED->GREEN: missing_strategies + risk_areas name REAL corpus nodes (were [])."""

    def test_missing_strategies_name_real_corpus_strategies(self, accessor_ids):
        kb = get_knowledge()
        res = evaluate_coverage(
            test_descriptions=_TESTS,
            system_description=_SYS,
            matched_signal_ids=accessor_ids["strategy"],
        )
        assert res["retrieval_state"] in ("hit", "low_confidence")
        missing = res["missing_strategies"]
        assert missing, "missing_strategies was always [] before the recommended_strategy fix"
        # Every named strategy resolves to a genuine corpus node — not a husk, not a
        # phantom, not a rubric category.
        for m in missing:
            assert kb.get_strategy(m["strategy_id"]) is not None, \
                f"missing strategy {m['strategy_id']!r} is not a real corpus node"
            assert m.get("category"), "a recommended corpus strategy carries its OWN category"
        assert any(m["strategy_id"] == "unit_isolation" for m in missing)

    def test_risk_areas_name_real_corpus_nodes(self, accessor_ids):
        kb = get_knowledge()
        res = evaluate_coverage(
            test_descriptions=_TESTS,
            system_description=_SYS,
            matched_signal_ids=accessor_ids["strategy"] + [accessor_ids["pattern"]],
        )
        # A corpus-sourced risk area names a real strategy or agent-pattern node —
        # not merely one of the 9 hardcoded rubric categories.
        corpus_risks = [r for r in res["risk_areas"]
                        if r.get("node_kind") in ("strategy", "agent_pattern")]
        assert corpus_risks, "risk_areas named only rubric categories before the retrofit"
        for r in corpus_risks:
            if r["node_kind"] == "agent_pattern":
                assert kb.get_pattern(r["node_id"]) is not None
                assert r.get("severity"), "an agent-pattern risk carries its OWN severity"
            else:
                assert kb.get_strategy(r["node_id"]) is not None

    def test_agent_pattern_risk_severity_is_the_nodes_own(self, accessor_ids):
        kb = get_knowledge()
        target = accessor_ids["pattern_ids"][0]
        res = evaluate_coverage(
            test_descriptions=_TESTS,
            system_description=_SYS,
            matched_signal_ids=accessor_ids["strategy"] + [accessor_ids["pattern"]],
        )
        assert res["agent_pattern_state"] in ("hit", "low_confidence")
        block = next((r for r in res["risk_areas"]
                      if r.get("node_kind") == "agent_pattern" and r["node_id"] == target), None)
        assert block is not None, "the recommended agent pattern must surface as a risk area"
        assert block["severity"] == kb.get_pattern(target).get("severity")


class TestDefaultCategoriesDemotedToWeights:
    """_DEFAULT_CATEGORIES supplies weights only; the corpus `category` supplies content."""

    def test_corpus_category_appears_with_its_recommended_strategies(self, accessor_ids):
        res = evaluate_coverage(
            test_descriptions=_TESTS,
            system_description=_SYS,
            matched_signal_ids=accessor_ids["strategy"],
        )
        cbc = res["coverage_by_category"]
        # "unit" is a corpus strategy category the hardcoded rubric never held.
        assert "unit" not in _DEFAULT_CATEGORIES
        assert "unit" in cbc, "corpus category 'unit' must supply content into coverage_by_category"
        unit = cbc["unit"]
        assert unit["source"] in ("corpus", "both")
        rec_ids = {s["strategy_id"] for s in unit["recommended_strategies"]}
        assert "unit_isolation" in rec_ids, "the category names its real recommended corpus strategy"

    def test_rubric_categories_keep_their_weights(self):
        # The rubric survives as the scoring lens: its recommended_min + priority still
        # drive the gap arithmetic for the categories it defines.
        res = evaluate_coverage(
            test_descriptions=_TESTS,
            system_description=_SYS,
            matched_signal_ids=[],
        )
        cbc = res["coverage_by_category"]
        for name, weight in _DEFAULT_CATEGORIES.items():
            assert name in cbc, f"rubric weight category {name!r} must remain a scoring lens"
            assert cbc[name]["recommended"] == weight["recommended_min"]
            assert cbc[name]["priority"] == weight["priority"]


class TestFailClosed:
    """Unrecognised ids abstain to honest empty — no fabricated corpus node."""

    def test_unrecognised_ids_yield_no_corpus_content(self):
        res = evaluate_coverage(
            test_descriptions=_TESTS,
            system_description=_SYS,
            matched_signal_ids=["sig-deadbeef0000"],
        )
        assert res["retrieval_state"] == "no_match"
        assert res["agent_pattern_state"] == "no_match"
        assert res["missing_strategies"] == []
        # No corpus-node risk area is fabricated; the rubric lens may still report
        # gaps for the provided tests, but names no strategy/pattern node.
        assert not any(r.get("node_kind") in ("strategy", "agent_pattern")
                       for r in res["risk_areas"])
        assert res["unmatched_signals"] == ["sig-deadbeef0000"]

    def test_empty_signals_is_rubric_only_not_a_crash(self):
        res = evaluate_coverage(
            test_descriptions=_TESTS,
            system_description=_SYS,
            matched_signal_ids=[],
        )
        assert res["retrieval_state"] == "no_match"
        assert res["missing_strategies"] == []
        assert res["coverage_by_category"], "the rubric scoring lens still runs with no signals"


class TestMatcherCallerRetired:
    """S5 dependency: evaluate_coverage no longer calls the legacy substring matcher."""

    def test_tool_no_longer_calls_match_structural_signals(self):
        mod = sys.modules[evaluate_coverage.__module__]
        assert "match_structural_signals(" not in inspect.getsource(mod)
