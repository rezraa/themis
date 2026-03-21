# Copyright (c) 2026 Reza Malik. Licensed under the Apache License, Version 2.0.
"""Tests for Themis tools — plan_test_strategy, judge_output, evaluate_coverage, log_verdict."""

from __future__ import annotations

import json
import pytest

from themis.tools.plan_test_strategy import plan_test_strategy
from themis.tools.judge_output import judge_output, _token_overlap_ratio
from themis.tools.evaluate_coverage import evaluate_coverage
from themis.tools.log_verdict import log_verdict


class TestPlanTestStrategy:
    """Test the strategy planning tool."""

    def test_matches_unit_test_signals(self):
        result = plan_test_strategy(
            system_description="Pure function that validates email addresses",
            structural_signals=["testing isolated function logic with known inputs"],
        )
        assert len(result["matched_rules"]) >= 1
        rule = result["matched_rules"][0]
        assert rule["rule_id"] == "rule_001"
        assert rule["recommended"] == "unit_parameterized"

    def test_returns_strategies_and_frameworks(self):
        result = plan_test_strategy(
            system_description="REST API with database",
            structural_signals=["testing isolated function logic"],
        )
        assert "recommended_strategies" in result
        assert "frameworks" in result

    def test_detects_agent_patterns(self):
        # Agent patterns trigger on hyphenated signal keywords like "tool-use", "multi-turn"
        result = plan_test_strategy(
            system_description="AI agent that calls tools and generates responses",
            structural_signals=["tool-use", "multi-turn"],
        )
        assert "agent_patterns" in result
        assert len(result["agent_patterns"]) >= 2
        pattern_names = [p["pattern"] for p in result["agent_patterns"]]
        assert "tool_call_validation" in pattern_names
        assert "conversation_coherence" in pattern_names

    def test_empty_signals_returns_empty(self):
        result = plan_test_strategy(
            system_description="Something",
            structural_signals=[],
        )
        assert result["matched_rules"] == []

    def test_constraints_filter(self):
        result = plan_test_strategy(
            system_description="Fast API endpoint",
            structural_signals=["testing isolated function logic with known inputs"],
            constraints={"max_setup_complexity": "low"},
        )
        # plan_test_strategy filters by its own complexity logic
        # Verify the result structure is valid
        assert "matched_rules" in result
        assert "recommended_strategies" in result
        assert "filtered_out" in result


class TestJudgeOutput:
    """Test the output judging engine."""

    def test_exact_match_pass(self):
        result = judge_output(
            test_case={"input": "2+2", "expected_output": "4", "test_type": "exact"},
            actual_output="4",
        )
        assert result["verdict"] == "pass"
        assert result["score"] == 1.0

    def test_exact_match_fail(self):
        result = judge_output(
            test_case={"input": "2+2", "expected_output": "4", "test_type": "exact"},
            actual_output="5",
        )
        assert result["verdict"] == "fail"
        assert result["score"] == 0.0
        assert len(result["deviations"]) > 0

    def test_contains_pass(self):
        result = judge_output(
            test_case={
                "input": "What is Python?",
                "expected_output": "programming language",
                "test_type": "contains",
            },
            actual_output="Python is a programming language created by Guido.",
        )
        assert result["verdict"] == "pass"
        assert result["score"] == 1.0

    def test_contains_fail(self):
        result = judge_output(
            test_case={
                "input": "What is Python?",
                "expected_output": "compiled language",
                "test_type": "contains",
            },
            actual_output="Python is an interpreted scripting language.",
        )
        assert result["verdict"] == "fail"

    def test_similarity_high_overlap(self):
        result = judge_output(
            test_case={
                "input": "test",
                "expected_output": "the quick brown fox jumps over the lazy dog",
                "test_type": "similarity",
            },
            actual_output="the quick brown fox leaps over the lazy dog",
            criteria={"similarity_threshold": 0.5},
        )
        assert result["score"] >= 0.5
        assert result["verdict"] in ("pass", "warning")

    def test_similarity_no_overlap(self):
        result = judge_output(
            test_case={
                "input": "test",
                "expected_output": "alpha beta gamma",
                "test_type": "similarity",
            },
            actual_output="one two three",
        )
        assert result["score"] < 0.1
        assert result["verdict"] == "fail"

    def test_json_structure_match(self):
        expected = json.dumps({"name": "test", "value": 42, "items": [1, 2]})
        actual = json.dumps({"name": "other", "value": 99, "items": [3, 4]})
        result = judge_output(
            test_case={
                "input": "test",
                "expected_output": expected,
                "test_type": "json_structure",
            },
            actual_output=actual,
        )
        assert result["verdict"] == "pass"
        assert result["score"] == 1.0

    def test_json_structure_mismatch(self):
        expected = json.dumps({"name": "test", "value": 42})
        actual = json.dumps({"name": "test"})
        result = judge_output(
            test_case={
                "input": "test",
                "expected_output": expected,
                "test_type": "json_structure",
            },
            actual_output=actual,
        )
        assert result["verdict"] != "pass"
        assert len(result["deviations"]) > 0

    def test_regex_match(self):
        result = judge_output(
            test_case={
                "input": "test",
                "expected_output": "",
                "expected_pattern": r"\d{3}-\d{4}",
                "test_type": "regex",
            },
            actual_output="Call me at 555-1234 anytime.",
        )
        assert result["verdict"] == "pass"

    def test_tool_call_validation(self):
        result = judge_output(
            test_case={
                "input": "test",
                "expected_output": "",
                "test_type": "tool_calls",
                "expected_tool_calls": [
                    {"name": "search", "arguments": {"query": "python"}},
                    {"name": "summarize"},
                ],
                "actual_tool_calls": [
                    {"name": "search", "arguments": {"query": "python"}},
                    {"name": "summarize"},
                ],
            },
            actual_output="Summary of results.",
        )
        assert result["verdict"] == "pass"
        assert result["tool_call_analysis"]["sequence_match"] is True

    def test_tool_call_wrong_order(self):
        result = judge_output(
            test_case={
                "input": "test",
                "expected_output": "",
                "test_type": "tool_calls",
                "expected_tool_calls": [
                    {"name": "search"},
                    {"name": "summarize"},
                ],
                "actual_tool_calls": [
                    {"name": "summarize"},
                    {"name": "search"},
                ],
            },
            actual_output="Results.",
        )
        assert result["verdict"] == "fail"
        assert result["tool_call_analysis"]["sequence_match"] is False

    def test_token_budget_within_limit(self):
        result = judge_output(
            test_case={
                "input": "test",
                "expected_output": "answer",
                "test_type": "exact",
                "token_budget": 1000,
                "actual_tokens_used": 500,
            },
            actual_output="answer",
        )
        assert result["token_usage_analysis"]["exceeded"] is False

    def test_token_budget_exceeded(self):
        result = judge_output(
            test_case={
                "input": "test",
                "expected_output": "answer",
                "test_type": "exact",
                "token_budget": 100,
                "actual_tokens_used": 200,
            },
            actual_output="answer",
        )
        assert result["token_usage_analysis"]["exceeded"] is True
        assert len(result["deviations"]) > 0


class TestTokenOverlap:
    """Test the token overlap similarity function."""

    def test_identical_strings(self):
        assert _token_overlap_ratio("hello world", "hello world") == 1.0

    def test_empty_strings(self):
        assert _token_overlap_ratio("", "") == 1.0

    def test_no_overlap(self):
        assert _token_overlap_ratio("alpha beta", "gamma delta") == 0.0

    def test_partial_overlap(self):
        ratio = _token_overlap_ratio("the cat sat", "the dog sat")
        assert 0.3 < ratio < 0.8  # 2/4 overlap


class TestEvaluateCoverage:
    """Test the coverage evaluation tool."""

    def test_finds_gaps(self):
        result = evaluate_coverage(
            test_descriptions=[
                {"name": "test_login", "category": "functional", "what_it_tests": "login"},
            ],
            system_description="Web app with auth, API, and database",
        )
        assert len(result["risk_areas"]) > 0
        assert "recommendations" in result

    def test_full_coverage(self):
        result = evaluate_coverage(
            test_descriptions=[
                {"name": f"test_{cat}", "category": cat, "what_it_tests": cat}
                for cat in [
                    "functional", "edge_cases", "error_handling", "performance",
                    "safety", "consistency", "multi_turn", "regression", "tool_usage",
                ]
            ],
            system_description="Some system",
        )
        assert result["coverage_by_category"] is not None


class TestLogVerdict:
    """Test verdict logging."""

    def test_log_verdict_json_mode(self, tmp_path):
        import os
        os.environ["THEMIS_DATA_DIR"] = str(tmp_path)

        result = log_verdict(
            mode="agent_test",
            system_tested="test_agent",
            verdict="pass",
            details={"score": 0.95, "test_count": 5},
        )
        assert result["verdict_id"] is not None
        assert result["storage_mode"] == "json"

        # Clean up
        del os.environ["THEMIS_DATA_DIR"]
