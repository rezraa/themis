# Copyright (c) 2026 Reza Malik. Licensed under the Apache License, Version 2.0.
"""Themis S5 deletion gate (story-9e3ae299; council 25d9a8ea / m-6ce2dcc3).

The lossy substring matcher and its rule-specific machinery are GONE at zero live
callers — the corpus's own signals are the single source of truth. This gate binds the
deletion so no shim/alias can quietly reintroduce a second retrieval path:

  * the loader carries none of ``match_structural_signals`` / ``_rule_signal_index`` /
    ``rules_for_strategy`` / ``_strategy_rule_index`` / ``_rules`` / ``_decision_rules_data``;
  * no file under src/themis names any of those symbols (grep-clean; no wrapper);
  * the loader no longer OPENS decision_rules.json (the src load is dead);
  * plan_test_strategy no longer emits ``matched_rules`` (the S3 forward-tension resolved
    by dropping the decision-rule provenance — the recommended strategies carry their OWN
    ``applies_when`` / ``avoid_when`` / ``trade_offs``, so no second why-source is folded);
  * decision_rules.json the FILE stays on disk, byte-identical to the frozen benchmark
    pin (freeze_manifest_v2 sha 650b4deb…) — deleted from the LOAD path only, kept as
    sha-pinned benchmark substrate.

Directive 8: ids come from the LIVE get_signal_index accessor, never a hand fixture.
Firewall: themis.* only. No live DB opened; the re-frozen recall guard is test_gmetric_s2.
"""

from __future__ import annotations

import json
from pathlib import Path

from themis.knowledge.loader import KnowledgeLoader
from themis.tools.get_signal_index import get_signal_index
from themis.tools.plan_test_strategy import plan_test_strategy

REPO = Path(__file__).resolve().parents[1]
SRC = REPO / "src" / "themis"
KDIR = SRC / "knowledge"
GMETRIC = REPO / "tests" / "data" / "gmetric"

# The rule-specific machinery deleted at S5 (north star). Instance attrs + src symbols.
_DELETED_ATTRS = (
    "match_structural_signals", "rules_for_strategy",
    "_rule_signal_index", "_strategy_rule_index",
    "_rules", "_decision_rules_data",
)
# Symbols that must not survive anywhere in production code (no shim/alias).
_DELETED_SYMBOLS = (
    "match_structural_signals", "rules_for_strategy",
    "_rule_signal_index", "_strategy_rule_index",
)


def _loader() -> KnowledgeLoader:
    return KnowledgeLoader(knowledge_dir=KDIR)


class TestLoaderMachineryGone:
    def test_loader_has_no_rule_machinery(self):
        kb = _loader()
        for attr in _DELETED_ATTRS:
            assert not hasattr(kb, attr), f"loader still carries {attr}"

    def test_loader_does_not_open_decision_rules(self):
        """The decision_rules src LOAD is dead — the loader never opens the file."""
        assert "decision_rules.json" not in (KDIR / "loader.py").read_text(encoding="utf-8")


class TestZeroReferencesNoShim:
    def test_no_src_file_names_a_deleted_symbol(self):
        hits = {}
        for p in SRC.rglob("*.py"):
            text = p.read_text(encoding="utf-8")
            named = [s for s in _DELETED_SYMBOLS if s in text]
            if named:
                hits[str(p)] = named
        assert hits == {}, f"deleted symbols still referenced in src: {hits}"

    def test_no_matcher_or_reverse_lookup_definition(self):
        for p in SRC.rglob("*.py"):
            text = p.read_text(encoding="utf-8")
            assert "def match_structural_signals" not in text
            assert "def rules_for_strategy" not in text


class TestPlanTestStrategyContract:
    def test_matched_rules_dropped(self):
        idx = get_signal_index()
        strat = [e["signal_id"] for e in idx["strategy_signals"]
                 if "unit_isolation" in e["strategy_ids"]][:2]
        assert len(strat) == 2
        res = plan_test_strategy(
            system_description="a pure function under test",
            structural_signals=strat,
        )
        assert "matched_rules" not in res
        # Retrieval still reasons over each node's OWN fields (unchanged from S3).
        rec = res["recommended_strategies"]
        ui = next(r for r in rec if r["strategy_id"] == "unit_isolation")
        assert ui["applies_when"] and ui["avoid_when"] and ui["trade_offs"]
        assert "pytest" in res["frameworks"]

    def test_no_match_abstains_without_matched_rules(self):
        res = plan_test_strategy(system_description="x", structural_signals=["sig-deadbeef0000"])
        assert res["retrieval_state"] == "no_match"
        assert res["recommended_strategies"] == []
        assert "matched_rules" not in res


class TestDecisionRulesFileKeptAsSubstrate:
    def test_file_present_and_byte_pinned(self):
        import hashlib
        f = KDIR / "decision_rules.json"
        assert f.exists(), "decision_rules.json must stay on disk as frozen benchmark substrate"
        pin = json.loads((GMETRIC / "freeze_manifest_v2.json").read_text(encoding="utf-8"))["pins"]
        cur = hashlib.sha256(f.read_bytes()).hexdigest()
        assert cur == pin["decision_rules.json"], "decision_rules.json drifted from its frozen pin"
