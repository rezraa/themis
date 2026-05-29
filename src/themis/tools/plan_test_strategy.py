# Copyright (c) 2026 Reza Malik. Licensed under the Apache License, Version 2.0.
"""MCP tool: plan_test_strategy

Recommend testing strategies based on agent-identified structural signals,
system description, and optional constraints.

The agent (LLM) reads the system/code and identifies testing signals.  This
tool matches those signals against decision_rules.json, retrieves knowledge
slices, filters by constraints (language, max_setup_complexity, etc.), and
detects agent-specific testing patterns.
"""

from __future__ import annotations

from typing import Any

from themis.tools._shared import coerce, emit_event, get_knowledge

# Sentinel distinguishing "argument omitted" from an explicit None/empty value,
# so a missing required signal fails loud instead of silently defaulting.
_MISSING = object()

# ---------------------------------------------------------------------------
# Agent testing signal keywords — triggers agent_patterns in output
# ---------------------------------------------------------------------------

_AGENT_SIGNALS: set[str] = {
    "tool-use",
    "multi-turn",
    "chain-of-thought",
    "planning",
    "retrieval-augmented",
    "function-calling",
    "streaming",
    "context-window",
    "guardrails",
    "hallucination-risk",
    "token-budget",
    "latency-sensitive",
    "multi-agent",
    "memory-persistence",
    "role-adherence",
}

# Built-in agent testing patterns — returned when agent signals are detected
_AGENT_PATTERNS: dict[str, dict[str, Any]] = {
    "tool-use": {
        "pattern": "tool_call_validation",
        "description": "Validate that the agent calls the correct tools with correct arguments",
        "strategies": ["exact_tool_match", "argument_schema_check", "tool_sequence_order"],
    },
    "multi-turn": {
        "pattern": "conversation_coherence",
        "description": "Test that multi-turn context is maintained across exchanges",
        "strategies": ["context_retention", "reference_resolution", "state_tracking"],
    },
    "chain-of-thought": {
        "pattern": "reasoning_trace",
        "description": "Validate reasoning steps are present and logically sound",
        "strategies": ["step_count_check", "logical_flow", "conclusion_grounding"],
    },
    "function-calling": {
        "pattern": "function_call_validation",
        "description": "Validate function call format, argument types, and return handling",
        "strategies": ["schema_compliance", "error_handling", "return_processing"],
    },
    "streaming": {
        "pattern": "stream_integrity",
        "description": "Validate streaming responses are complete and well-formed",
        "strategies": ["chunk_completeness", "final_assembly", "timeout_handling"],
    },
    "hallucination-risk": {
        "pattern": "factual_grounding",
        "description": "Check outputs against known facts and source material",
        "strategies": ["source_attribution", "claim_verification", "refusal_on_unknown"],
    },
    "token-budget": {
        "pattern": "budget_compliance",
        "description": "Verify agent stays within token/cost budgets",
        "strategies": ["token_counting", "cost_estimation", "truncation_check"],
    },
    "latency-sensitive": {
        "pattern": "latency_profiling",
        "description": "Measure and validate response latency against SLAs",
        "strategies": ["p50_p99_measurement", "timeout_enforcement", "degradation_curve"],
    },
    "guardrails": {
        "pattern": "safety_boundary",
        "description": "Test that guardrails prevent disallowed outputs",
        "strategies": ["injection_resistance", "role_boundary", "output_filtering"],
    },
    "multi-agent": {
        "pattern": "orchestration_validation",
        "description": "Validate multi-agent coordination, handoffs, and results",
        "strategies": ["handoff_correctness", "result_aggregation", "deadlock_detection"],
    },
    "memory-persistence": {
        "pattern": "memory_integrity",
        "description": "Test that agent memory persists correctly across sessions",
        "strategies": ["recall_accuracy", "decay_behaviour", "conflict_resolution"],
    },
    "role-adherence": {
        "pattern": "persona_consistency",
        "description": "Validate the agent maintains its assigned role/persona",
        "strategies": ["tone_check", "boundary_enforcement", "instruction_following"],
    },
}

# ---------------------------------------------------------------------------
# Constraint filters
# ---------------------------------------------------------------------------

_COMPLEXITY_RANK: dict[str, int] = {
    "trivial": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
    "extreme": 4,
}


def _complexity_ok(strategy_complexity: str, max_allowed: str) -> bool:
    """Return True if the strategy complexity is within the allowed threshold."""
    s = _COMPLEXITY_RANK.get(strategy_complexity.lower(), 2)
    m = _COMPLEXITY_RANK.get(max_allowed.lower(), 4)
    return s <= m


def _language_ok(strategy: dict[str, Any], language: str) -> bool:
    """Return True if the strategy supports the given language."""
    supported = strategy.get("languages")
    if not supported:
        return True  # language-agnostic strategy
    return language.lower() in [lang.lower() for lang in supported]


# ---------------------------------------------------------------------------
# Main tool
# ---------------------------------------------------------------------------

def plan_test_strategy(
    system_description: Any = _MISSING,
    structural_signals: Any = _MISSING,
    constraints: dict | None = None,
    conn: object = None,
    **extra: Any,
) -> dict:
    """Recommend testing strategies based on structural signals and constraints.

    Args:
        system_description: Description of what needs testing — the system,
            API, agent, or code under test.
        structural_signals: Agent-identified signals, e.g.
            ["tool-use", "multi-turn", "latency-sensitive", "rest-api"].
            Required — a missing value raises rather than silently defaulting,
            since an empty signal set would mask a caller bug.
        constraints: Optional dict with keys like ``language``,
            ``max_setup_complexity`` ("low"/"medium"/"high"/"extreme"),
            ``max_strategies`` (int), ``framework_preference`` (str).
        conn: Kuzu/LadybugDB connection for graph mode, or None for JSON.

    Returns:
        Dict with keys: matched_rules, recommended_strategies, frameworks,
        alternatives, filtered_out, agent_patterns (if agent signals found).
    """
    # Recover a lone stray string -> system_description when the caller sent
    # exactly one extra string and system_description was not supplied.
    if system_description is _MISSING and extra:
        stray_strings = [k for k, v in extra.items() if isinstance(v, str)]
        if len(extra) == 1 and len(stray_strings) == 1:
            system_description = extra.pop(stray_strings[0])
    if extra:
        raise TypeError(
            "plan_test_strategy() got unexpected keyword argument(s): "
            + ", ".join(sorted(extra))
        )
    if system_description is _MISSING:
        raise TypeError(
            "plan_test_strategy() missing required argument 'system_description'"
        )
    if structural_signals is _MISSING:
        raise TypeError(
            "plan_test_strategy requires 'structural_signals' (a list of "
            "agent-identified testing signals); refusing to default it to [] "
            "as that would mask a caller bug"
        )

    structural_signals = coerce(structural_signals, list, default=[])
    constraints = coerce(constraints, dict, default={})

    kb = get_knowledge(conn)

    # 1. Match structural signals against decision rules
    matched_rules: list[dict[str, Any]] = []
    recommended_strategies: list[dict[str, Any]] = []
    alternatives: list[dict[str, Any]] = []

    if structural_signals:
        rule_matches = kb.match_structural_signals(structural_signals)
        for rm in rule_matches:
            rule = rm["rule"]
            rec = rm.get("recommended_strategy") or rm.get("recommended_pattern")

            rule_entry: dict[str, Any] = {
                "signal": rm["signal"],
                "rule_id": rule["id"],
                "recommended": rule.get("recommended_strategy", "") or rule.get("recommended_pattern", ""),
                "description": rule.get("description", ""),
                "alternatives": [a.get("id", "") for a in rm.get("alternatives", [])],
            }
            matched_rules.append(rule_entry)

            # Build recommended strategy from the matched pattern
            if rec:
                strategy: dict[str, Any] = {
                    "strategy_id": rec["id"],
                    "name": rec.get("name", rec["id"]),
                    "description": rec.get("description", ""),
                    "setup_complexity": rec.get("setup_complexity", "medium"),
                    "languages": rec.get("languages", []),
                    "frameworks": rec.get("frameworks", []),
                    "source": "decision_rule",
                    "rule_id": rule["id"],
                    "score": 1.0,
                }
                recommended_strategies.append(strategy)

            # Collect alternatives
            for alt in rm.get("alternatives", []):
                alt_entry: dict[str, Any] = {
                    "strategy_id": alt["id"],
                    "name": alt.get("name", alt["id"]),
                    "description": alt.get("description", ""),
                    "setup_complexity": alt.get("setup_complexity", "medium"),
                    "languages": alt.get("languages", []),
                    "frameworks": alt.get("frameworks", []),
                    "source": "alternative",
                    "rule_id": rule["id"],
                    "score": 0.6,
                }
                alternatives.append(alt_entry)

    # 2. Filter by constraints
    filtered_out: list[dict[str, Any]] = []
    max_complexity = constraints.get("max_setup_complexity")
    language = constraints.get("language")
    max_strategies = constraints.get("max_strategies")
    framework_pref = constraints.get("framework_preference")

    def _apply_filters(
        strategies: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        surviving: list[dict[str, Any]] = []
        for s in strategies:
            # Complexity filter
            if max_complexity:
                sc = s.get("setup_complexity", "medium")
                if not _complexity_ok(sc, max_complexity):
                    filtered_out.append({
                        "strategy_id": s.get("strategy_id", ""),
                        "name": s.get("name", ""),
                        "reason": f"setup_complexity '{sc}' exceeds max '{max_complexity}'",
                    })
                    continue

            # Language filter
            if language and not _language_ok(s, language):
                filtered_out.append({
                    "strategy_id": s.get("strategy_id", ""),
                    "name": s.get("name", ""),
                    "reason": f"language '{language}' not supported",
                })
                continue

            # Framework preference — boost score rather than filter
            if framework_pref:
                fws = [f.lower() for f in s.get("frameworks", [])]
                if framework_pref.lower() in fws:
                    s["score"] = s.get("score", 0.6) + 0.2

            surviving.append(s)
        return surviving

    recommended_strategies = _apply_filters(recommended_strategies)
    alternatives = _apply_filters(alternatives)

    # Sort by score descending
    recommended_strategies.sort(key=lambda s: -s.get("score", 0))
    alternatives.sort(key=lambda s: -s.get("score", 0))

    # Enforce max_strategies limit
    if max_strategies and isinstance(max_strategies, int):
        overflow = recommended_strategies[max_strategies:]
        recommended_strategies = recommended_strategies[:max_strategies]
        # Overflow from recommended becomes alternatives
        for item in overflow:
            item["source"] = "overflow"
            item["score"] = max(item.get("score", 0) - 0.1, 0)
        alternatives = overflow + alternatives

    # 3. Detect agent-specific testing patterns
    agent_patterns: list[dict[str, Any]] = []
    detected_agent_signals: list[str] = []
    for signal in structural_signals:
        sig_lower = signal.lower()
        if sig_lower in _AGENT_SIGNALS:
            detected_agent_signals.append(sig_lower)
            pattern_info = _AGENT_PATTERNS.get(sig_lower)
            if pattern_info:
                agent_patterns.append({
                    "signal": sig_lower,
                    **pattern_info,
                })

    # 4. Collect unique frameworks across all recommended strategies
    frameworks: list[str] = []
    seen_fw: set[str] = set()
    for s in recommended_strategies:
        for fw in s.get("frameworks", []):
            fw_lower = fw.lower()
            if fw_lower not in seen_fw:
                seen_fw.add(fw_lower)
                frameworks.append(fw)

    # 5. Build result
    result: dict[str, Any] = {
        "matched_rules": matched_rules,
        "recommended_strategies": recommended_strategies,
        "frameworks": frameworks,
        "alternatives": alternatives,
        "filtered_out": filtered_out,
    }

    if agent_patterns:
        result["agent_patterns"] = agent_patterns
        result["agent_signals_detected"] = detected_agent_signals

    emit_event("plan_test_strategy", {
        "system_description": system_description[:120],
        "signals": structural_signals,
        "matched_rules_count": len(matched_rules),
        "strategies_count": len(recommended_strategies),
        "agent_patterns_count": len(agent_patterns),
        "filtered_out_count": len(filtered_out),
    })

    return result
