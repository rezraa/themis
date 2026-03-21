# Copyright (c) 2026 Reza Malik. Licensed under the Apache License, Version 2.0.
"""Tests for Themis knowledge base — strategies, patterns, rules, frameworks."""

from __future__ import annotations

import pytest

from themis.knowledge.loader import KnowledgeLoader


@pytest.fixture(scope="module")
def kb():
    return KnowledgeLoader()


class TestKnowledgeLoading:
    """Verify all JSON files load and index correctly."""

    def test_strategies_loaded(self, kb):
        strategies = kb.get_all_strategies()
        assert len(strategies) >= 40, f"Expected 40+ strategies, got {len(strategies)}"

    def test_agent_patterns_loaded(self, kb):
        patterns = kb.get_all_agent_patterns()
        assert len(patterns) >= 12, f"Expected 12+ agent patterns, got {len(patterns)}"

    def test_frameworks_loaded(self, kb):
        frameworks = kb.get_all_frameworks()
        assert len(frameworks) >= 15, f"Expected 15+ frameworks, got {len(frameworks)}"

    def test_decision_rules_loaded(self, kb):
        assert len(kb._rules) >= 35, f"Expected 35+ rules, got {len(kb._rules)}"

    def test_strategies_have_required_fields(self, kb):
        for s in kb.get_all_strategies():
            assert "id" in s, f"Strategy missing id: {s}"
            assert "name" in s, f"Strategy missing name: {s.get('id')}"
            assert "category" in s, f"Strategy missing category: {s.get('id')}"
            assert "structural_signals" in s, f"Strategy missing signals: {s.get('id')}"

    def test_agent_patterns_have_required_fields(self, kb):
        for p in kb.get_all_agent_patterns():
            assert "id" in p
            assert "name" in p
            assert "severity" in p
            assert "test_approach" in p
            assert "adapters" in p

    def test_frameworks_have_required_fields(self, kb):
        for f in kb.get_all_frameworks():
            assert "id" in f
            assert "name" in f
            assert "language" in f
            assert "categories" in f


class TestStrategyRetrieval:
    """Test strategy lookup and filtering."""

    def test_get_strategy_by_id(self, kb):
        s = kb.get_strategy("unit_parameterized")
        assert s is not None
        assert s["name"] == "Unit Test — Parameterized" or "Parameterized" in s["name"]

    def test_get_strategy_not_found(self, kb):
        s = kb.get_strategy("nonexistent_strategy")
        assert s is None

    def test_get_strategies_by_category(self, kb):
        unit = kb.get_strategies_by_category("unit")
        assert len(unit) >= 3
        for s in unit:
            assert s["category"] == "unit"

    def test_get_agent_strategies(self, kb):
        agent = kb.get_strategies_by_category("agent")
        assert len(agent) >= 10
        for s in agent:
            assert s["category"] == "agent"

    def test_all_categories_present(self, kb):
        categories = {s["category"] for s in kb.get_all_strategies()}
        expected = {"unit", "integration", "e2e", "agent", "security", "load"}
        assert expected.issubset(categories), f"Missing categories: {expected - categories}"


class TestFrameworkRetrieval:
    """Test framework lookup."""

    def test_get_framework_by_id(self, kb):
        f = kb.get_framework("pytest")
        assert f is not None
        assert f["language"] == "python"

    def test_get_frameworks_by_language(self, kb):
        py = kb.get_frameworks_by_language("python")
        assert len(py) >= 2
        for f in py:
            assert f["language"] == "python" or f["language"] == "multi"

    def test_get_frameworks_with_agent_support(self, kb):
        agent_fw = kb.get_frameworks_with_agent_support()
        assert len(agent_fw) >= 3
        for f in agent_fw:
            assert f.get("agent_testing_support") in ("native", "plugin")


class TestSignalMatching:
    """Test structural signal matching against decision rules."""

    def test_exact_signal_match(self, kb):
        matches = kb.match_structural_signals(
            ["testing isolated function logic with known inputs"]
        )
        assert len(matches) >= 1
        assert matches[0]["rule"]["recommended_strategy"] == "unit_parameterized"

    def test_substring_signal_match(self, kb):
        matches = kb.match_structural_signals(
            ["testing isolated function logic"]
        )
        assert len(matches) >= 1

    def test_no_match_for_gibberish(self, kb):
        matches = kb.match_structural_signals(["xyzzy foobar nonsense"])
        assert len(matches) == 0

    def test_multiple_signals(self, kb):
        matches = kb.match_structural_signals([
            "testing isolated function logic",
            "pure function with no side effects",
        ])
        assert len(matches) >= 2


class TestConstraintFiltering:
    """Test filtering strategies by constraints."""

    def test_filter_by_language(self, kb):
        all_s = kb.get_all_strategies()
        surviving, filtered = kb.filter_by_constraints(all_s, {"language": "python"})
        # All should survive since strategies aren't language-specific
        # (frameworks are, but strategies aren't filtered out by language)
        assert len(surviving) + len(filtered) == len(all_s)

    def test_filter_by_setup_complexity(self, kb):
        all_s = kb.get_all_strategies()
        surviving, filtered = kb.filter_by_constraints(
            all_s, {"max_setup": "low"}
        )
        # Surviving strategies should have setup complexity <= low
        for s in surviving:
            setup = s.get("complexity", {}).get("setup", "low")
            assert setup == "low", f"Strategy {s['id']} has setup={setup}"
        assert len(filtered) > 0, "Some strategies should be filtered out"

    def test_filter_returns_all_when_no_constraints(self, kb):
        all_s = kb.get_all_strategies()
        surviving, filtered = kb.filter_by_constraints(all_s, {})
        assert len(surviving) == len(all_s)
        assert len(filtered) == 0


class TestAlternatives:
    """Test alternative strategy resolution."""

    def test_get_alternatives(self, kb):
        alts = kb.get_alternatives("unit_parameterized")
        assert len(alts) >= 1
        alt_ids = [a["id"] for a in alts if isinstance(a, dict) and "id" in a]
        assert "unit_table_driven" in alt_ids or len(alts) > 0


class TestCompactIndex:
    """Test compact index for scanning."""

    def test_compact_index_returns_all(self, kb):
        index = kb.get_compact_index()
        all_s = kb.get_all_strategies()
        assert len(index) == len(all_s)

    def test_compact_index_has_signals(self, kb):
        index = kb.get_compact_index()
        for entry in index:
            assert "id" in entry
            assert "structural_signals" in entry
