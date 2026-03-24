# Copyright (c) 2026 Reza Malik. Licensed under the Apache License, Version 2.0.
"""Themis MCP Server -- Testing & Validation Titan.

Thin wrappers that delegate to tool modules in themis/tools/.
Same pattern as Phoebe/Mnemos: server registers tools, modules do the work.
"""

from __future__ import annotations

import json as _json
from typing import Any, Union

from fastmcp import FastMCP

from themis.tools.plan_test_strategy import plan_test_strategy as _plan_test_strategy
from themis.tools.judge_output import judge_output as _judge_output
from themis.tools.run_agent_test import run_agent_test as _run_agent_test
from themis.tools.evaluate_coverage import evaluate_coverage as _evaluate_coverage
from themis.tools.log_verdict import log_verdict as _log_verdict
from themis.tools._shared import coerce


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

mcp = FastMCP("themis", instructions=(
    "I am Themis, Titan of divine law. I judge what is correct and what is wrong. "
    "No opinion, just truth. "
    "I don't just run tests — I think about what should be tested. "
    "I read systems and identify the testing shape: inputs, invariants, failure modes, "
    "integration seams, and agent behavior boundaries. "
    "Things PASS or they FAIL. There is no 'maybe.' "
    "You didn't test the empty input. You never test the empty input."
))


# ---------------------------------------------------------------------------
# Tool registrations -- thin wrappers
# ---------------------------------------------------------------------------

@mcp.tool()
def plan_test_strategy(
    system_description: str,
    structural_signals: Union[list[str], str],
    constraints: Union[dict[str, Any], str, None] = None,
    conn: Any = None,
) -> dict:
    """Analyze a system and recommend the right testing strategy.

    Given a description of what to test and structural signals about its
    architecture, returns prioritized test categories, recommended frameworks,
    and specific test case outlines.

    Args:
        system_description: What the system does, its inputs/outputs, and
            architecture (the more specific, the better Themis's judgment).
        structural_signals: List of signals about the system's nature, e.g.
            ["async_pipeline", "user_input_validation", "database_writes",
             "agent_output", "rate_limited"].
        constraints: Optional dict of constraints like {"framework": "pytest",
            "time_budget_minutes": 30, "environment": "ci"}.
        conn: Kuzu/LadybugDB connection for graph mode (injected by Othrys).

    Returns: {strategies: [...], frameworks: [...], test_cases: [...],
              coverage_targets: [...], priority_order: [...]}
    """
    return _plan_test_strategy(
        system_description=system_description,
        structural_signals=coerce(structural_signals, list),
        constraints=coerce(constraints, dict),
        conn=conn,
    )


@mcp.tool()
def judge_output(
    test_case: Union[dict[str, Any], str],
    actual_output: str,
    criteria: Union[list[str], str, None] = None,
    conn: Any = None,
) -> dict:
    """Judge whether a test output is correct against defined criteria.

    For deterministic systems, checks exact or structural match.
    For agent output, evaluates semantic correctness, instruction-following,
    hallucination risk, and completeness.

    Args:
        test_case: The test case definition -- must include at minimum
            {"input": "...", "expected": "..."} or a description of
            what correct output looks like.
        actual_output: The actual output produced by the system under test.
        criteria: List of criteria to judge against, e.g.
            ["semantic_correctness", "no_hallucination",
             "follows_instructions", "complete_response"].
            If None, Themis infers appropriate criteria from the test case.
        conn: Kuzu/LadybugDB connection for graph mode (injected by Othrys).

    Returns: {verdict: "PASS"|"FAIL"|"WARN", score: 0.0-1.0,
              reasoning: "...", criteria_results: [...]}
    """
    return _judge_output(
        test_case=coerce(test_case, dict),
        actual_output=actual_output,
        criteria=coerce(criteria, list),
        conn=conn,
    )


@mcp.tool()
async def run_agent_test(
    agent_endpoint: str,
    adapter_type: str = "http",
    test_cases: Union[list[dict], str, None] = None,
    config: Union[dict[str, Any], str, None] = None,
    conn: Any = None,
) -> dict:
    """Run test cases against a live agent endpoint.

    Supports multiple adapter types for different agent protocols.
    Each test case is sent to the agent, the response is captured with
    timing data, and raw results are returned for judgment.

    Args:
        agent_endpoint: URL or address of the agent to test.
        adapter_type: Protocol adapter -- "http", "websocket", or "mcp".
        test_cases: List of test case dicts, each with at minimum
            {"input": "...", "expected": "..."}.
        config: Optional adapter config like {"timeout_seconds": 30,
            "headers": {"Authorization": "Bearer ..."}, "retries": 2}.
        conn: Kuzu/LadybugDB connection for graph mode (injected by Othrys).

    Returns: {agent: "...", adapter: "...", results: [{test_case, response,
              latency_ms, status_code, tokens_used}], summary: {...}}
    """
    return await _run_agent_test(
        agent_endpoint=agent_endpoint,
        adapter_type=adapter_type,
        test_cases=coerce(test_cases, list),
        config=coerce(config, dict),
        conn=conn,
    )


@mcp.tool()
def evaluate_coverage(
    test_descriptions: Union[list[str], str],
    system_description: str,
    structural_signals: Union[list[str], str],
    conn: Any = None,
) -> dict:
    """Evaluate how well existing tests cover a system.

    Compares what IS tested against what SHOULD be tested. Identifies
    gaps, redundancies, and priorities for new tests.

    Args:
        test_descriptions: List of plain-English descriptions of existing
            tests (e.g. ["tests login with valid credentials",
            "tests rate limit returns 429"]).
        system_description: Description of the system being tested.
        structural_signals: List of architectural signals about the system.
        conn: Kuzu/LadybugDB connection for graph mode (injected by Othrys).

    Returns: {coverage_score: 0.0-1.0, covered: [...], gaps: [...],
              redundant: [...], recommendations: [...]}
    """
    return _evaluate_coverage(
        test_descriptions=coerce(test_descriptions, list),
        system_description=system_description,
        structural_signals=coerce(structural_signals, list),
        conn=conn,
    )


@mcp.tool()
def log_verdict(
    mode: str,
    system_tested: str,
    verdict: str,
    details: Union[dict[str, Any], str, None] = None,
    conn: Any = None,
) -> dict:
    """Record a test verdict to the permanent log.

    Every judgment Themis makes is logged. The verdict log is append-only.
    What was judged stays judged.

    Args:
        mode: Testing mode used -- "unit", "integration", "agent", "coverage",
            "property", "e2e", "manual".
        system_tested: Name or identifier of the system that was tested.
        verdict: "PASS", "FAIL", or "WARN".
        details: Optional dict with additional context -- test counts,
            failure details, coverage scores, timing data, etc.
        conn: Kuzu/LadybugDB connection for graph mode (injected by Othrys).

    Returns: {logged: true, verdict_id: "...", timestamp: "..."}
    """
    return _log_verdict(
        mode=mode,
        system_tested=system_tested,
        verdict=verdict,
        details=coerce(details, dict),
        conn=conn,
    )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    mcp.run()


if __name__ == "__main__":
    main()
