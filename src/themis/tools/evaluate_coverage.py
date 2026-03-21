# Copyright (c) 2026 Reza Malik. Licensed under the Apache License, Version 2.0.
"""MCP tool: evaluate_coverage

Analyze test coverage gaps by comparing existing test descriptions against
the testing strategies recommended by the knowledge base.

Identifies missing strategies, risk areas, and specific tests to add.
"""

from __future__ import annotations

from typing import Any

from themis.tools._shared import coerce, emit_event, get_knowledge

# ---------------------------------------------------------------------------
# Standard testing categories and their recommended minimum coverage
# ---------------------------------------------------------------------------

_DEFAULT_CATEGORIES: dict[str, dict[str, Any]] = {
    "functional": {
        "description": "Core functionality and happy-path behaviour",
        "recommended_min": 3,
        "priority": "critical",
    },
    "edge_cases": {
        "description": "Boundary conditions, empty inputs, maximum values",
        "recommended_min": 2,
        "priority": "high",
    },
    "error_handling": {
        "description": "Invalid inputs, exceptions, graceful degradation",
        "recommended_min": 2,
        "priority": "high",
    },
    "tool_usage": {
        "description": "Tool call correctness, argument validation, sequences",
        "recommended_min": 2,
        "priority": "high",
    },
    "performance": {
        "description": "Latency, token usage, throughput under load",
        "recommended_min": 1,
        "priority": "medium",
    },
    "safety": {
        "description": "Guardrails, injection resistance, output filtering",
        "recommended_min": 2,
        "priority": "critical",
    },
    "consistency": {
        "description": "Determinism, persona adherence, format compliance",
        "recommended_min": 1,
        "priority": "medium",
    },
    "multi_turn": {
        "description": "Context retention, reference resolution across turns",
        "recommended_min": 1,
        "priority": "medium",
    },
    "regression": {
        "description": "Previously failing cases, known-bad inputs",
        "recommended_min": 1,
        "priority": "high",
    },
}

# Category aliases — normalise test descriptions into standard categories
_CATEGORY_ALIASES: dict[str, str] = {
    "happy_path": "functional",
    "happy-path": "functional",
    "basic": "functional",
    "core": "functional",
    "boundary": "edge_cases",
    "edge": "edge_cases",
    "corner_case": "edge_cases",
    "corner-case": "edge_cases",
    "error": "error_handling",
    "failure": "error_handling",
    "invalid": "error_handling",
    "exception": "error_handling",
    "tool": "tool_usage",
    "tools": "tool_usage",
    "function_call": "tool_usage",
    "function-call": "tool_usage",
    "latency": "performance",
    "speed": "performance",
    "throughput": "performance",
    "load": "performance",
    "token": "performance",
    "security": "safety",
    "guardrail": "safety",
    "guardrails": "safety",
    "injection": "safety",
    "prompt_injection": "safety",
    "prompt-injection": "safety",
    "determinism": "consistency",
    "format": "consistency",
    "persona": "consistency",
    "role": "consistency",
    "context": "multi_turn",
    "conversation": "multi_turn",
    "multi-turn": "multi_turn",
    "multiturn": "multi_turn",
    "regression": "regression",
    "known_bad": "regression",
    "known-bad": "regression",
}


def _normalise_category(raw: str) -> str:
    """Map a raw category string to a standard category name."""
    lower = raw.lower().strip().replace(" ", "_")
    return _CATEGORY_ALIASES.get(lower, lower)


def _infer_category(test_desc: dict[str, Any]) -> str:
    """Infer a standard category from test description fields."""
    # Explicit category
    cat = test_desc.get("category", "")
    if cat:
        return _normalise_category(cat)

    # Infer from name and what_it_tests
    name = test_desc.get("name", "").lower()
    what = test_desc.get("what_it_tests", "").lower()
    combined = f"{name} {what}"

    # Score each category by keyword overlap
    best_cat = "functional"  # default
    best_score = 0

    keywords_map: dict[str, list[str]] = {
        "functional": ["function", "basic", "happy", "core", "works", "returns", "output"],
        "edge_cases": ["edge", "boundary", "empty", "null", "zero", "max", "min", "overflow"],
        "error_handling": ["error", "invalid", "fail", "exception", "bad", "malformed", "reject"],
        "tool_usage": ["tool", "function_call", "call", "invoke", "argument", "sequence"],
        "performance": ["latency", "speed", "token", "budget", "timeout", "slow", "fast"],
        "safety": ["safety", "security", "inject", "guardrail", "filter", "block", "harmful"],
        "consistency": ["consistent", "deterministic", "format", "persona", "role", "tone"],
        "multi_turn": ["multi", "turn", "context", "conversation", "history", "remember"],
        "regression": ["regression", "known", "previous", "bug", "fixed"],
    }

    for cat_name, keywords in keywords_map.items():
        score = sum(1 for kw in keywords if kw in combined)
        if score > best_score:
            best_score = score
            best_cat = cat_name

    return best_cat


# ---------------------------------------------------------------------------
# Main tool
# ---------------------------------------------------------------------------

def evaluate_coverage(
    test_descriptions: list[dict],
    system_description: str,
    structural_signals: list[str] | None = None,
    conn: object = None,
) -> dict:
    """Analyze test coverage gaps against the knowledge base.

    Args:
        test_descriptions: List of dicts, each with:
            - ``name`` (str): Test name.
            - ``category`` (str): Test category (will be normalised).
            - ``what_it_tests`` (str): Description of what's tested.
        system_description: Description of the system under test.
        structural_signals: Optional signals for knowledge base matching.
        conn: Kuzu/LadybugDB connection for graph mode, or None.

    Returns:
        Dict with keys: coverage_by_category, missing_strategies,
        risk_areas, recommendations, summary.
    """
    test_descriptions = coerce(test_descriptions, list) or []
    structural_signals = coerce(structural_signals, list) or []

    kb = get_knowledge(conn)

    # 1. Categorise existing tests
    category_counts: dict[str, int] = {}
    categorised_tests: dict[str, list[str]] = {}

    for td in test_descriptions:
        cat = _infer_category(td)
        category_counts[cat] = category_counts.get(cat, 0) + 1
        categorised_tests.setdefault(cat, []).append(td.get("name", "unnamed"))

    # 2. Build coverage map against default categories
    coverage_by_category: dict[str, dict[str, Any]] = {}

    for cat_name, cat_info in _DEFAULT_CATEGORIES.items():
        covered = category_counts.get(cat_name, 0)
        recommended = cat_info["recommended_min"]
        gap = max(0, recommended - covered)

        coverage_by_category[cat_name] = {
            "description": cat_info["description"],
            "covered": covered,
            "recommended": recommended,
            "gap": gap,
            "priority": cat_info["priority"],
            "tests": categorised_tests.get(cat_name, []),
        }

    # Include any custom categories not in defaults
    for cat_name, count in category_counts.items():
        if cat_name not in _DEFAULT_CATEGORIES:
            coverage_by_category[cat_name] = {
                "description": f"Custom category: {cat_name}",
                "covered": count,
                "recommended": 1,
                "gap": 0,
                "priority": "low",
                "tests": categorised_tests.get(cat_name, []),
            }

    # 3. Match structural signals to find recommended strategies from KB
    kb_strategies: list[dict[str, Any]] = []
    if structural_signals:
        rule_matches = kb.match_structural_signals(structural_signals)
        for rm in rule_matches:
            rule = rm["rule"]
            rec = rm.get("recommended_pattern")
            if rec:
                kb_strategies.append({
                    "strategy_id": rec["id"],
                    "name": rec.get("name", rec["id"]),
                    "signal": rm["signal"],
                    "rule_id": rule["id"],
                })
            for alt in rm.get("alternatives", []):
                kb_strategies.append({
                    "strategy_id": alt["id"],
                    "name": alt.get("name", alt["id"]),
                    "signal": rm["signal"],
                    "rule_id": rule["id"],
                })

    # 4. Find missing strategies — KB strategies not covered by any test
    test_names_lower = {td.get("name", "").lower() for td in test_descriptions}
    test_whats_lower = {td.get("what_it_tests", "").lower() for td in test_descriptions}
    all_test_text = " ".join(test_names_lower | test_whats_lower)

    missing_strategies: list[dict[str, Any]] = []
    for strat in kb_strategies:
        strat_name = strat["name"].lower().replace("-", " ").replace("_", " ")
        # Check if any existing test seems to cover this strategy
        covered = any(
            token in all_test_text
            for token in strat_name.split()
            if len(token) > 3
        )
        if not covered:
            missing_strategies.append(strat)

    # 5. Identify risk areas — categories with gaps and high priority
    priority_rank = {"critical": 3, "high": 2, "medium": 1, "low": 0}
    risk_areas: list[dict[str, Any]] = []

    for cat_name, info in coverage_by_category.items():
        if info["gap"] > 0:
            risk_areas.append({
                "category": cat_name,
                "description": info["description"],
                "gap": info["gap"],
                "priority": info["priority"],
                "severity": "critical" if info["priority"] == "critical" and info["gap"] >= 2
                    else "high" if info["priority"] in ("critical", "high")
                    else "medium",
            })

    risk_areas.sort(
        key=lambda r: (-priority_rank.get(r["priority"], 0), -r["gap"]),
    )

    # 6. Generate specific recommendations
    recommendations: list[dict[str, Any]] = []

    for risk in risk_areas[:5]:  # Top 5 risk areas
        cat = risk["category"]
        cat_info = _DEFAULT_CATEGORIES.get(cat, {})
        gap = risk["gap"]

        for i in range(min(gap, 3)):  # Up to 3 recommendations per category
            rec: dict[str, Any] = {
                "category": cat,
                "priority": risk["priority"],
            }

            if cat == "functional":
                rec["suggested_test"] = f"test_{cat}_case_{i+1}"
                rec["description"] = "Add a test for core happy-path behaviour"
            elif cat == "edge_cases":
                edge_types = ["empty_input", "maximum_length", "special_characters"]
                rec["suggested_test"] = f"test_edge_{edge_types[i % len(edge_types)]}"
                rec["description"] = f"Add edge case test: {edge_types[i % len(edge_types)]}"
            elif cat == "error_handling":
                error_types = ["invalid_input", "malformed_json", "missing_required_field"]
                rec["suggested_test"] = f"test_error_{error_types[i % len(error_types)]}"
                rec["description"] = f"Add error handling test: {error_types[i % len(error_types)]}"
            elif cat == "tool_usage":
                tool_types = ["correct_tool_selected", "argument_validation", "tool_sequence"]
                rec["suggested_test"] = f"test_tool_{tool_types[i % len(tool_types)]}"
                rec["description"] = f"Add tool usage test: {tool_types[i % len(tool_types)]}"
            elif cat == "safety":
                safety_types = ["prompt_injection", "harmful_content_block", "pii_filtering"]
                rec["suggested_test"] = f"test_safety_{safety_types[i % len(safety_types)]}"
                rec["description"] = f"Add safety test: {safety_types[i % len(safety_types)]}"
            elif cat == "performance":
                rec["suggested_test"] = f"test_performance_{i+1}"
                rec["description"] = "Add latency/token budget test"
            elif cat == "consistency":
                rec["suggested_test"] = f"test_consistency_{i+1}"
                rec["description"] = "Add determinism or format compliance test"
            elif cat == "multi_turn":
                rec["suggested_test"] = f"test_multi_turn_{i+1}"
                rec["description"] = "Add multi-turn context retention test"
            elif cat == "regression":
                rec["suggested_test"] = f"test_regression_{i+1}"
                rec["description"] = "Add test for a previously known failure"
            else:
                rec["suggested_test"] = f"test_{cat}_{i+1}"
                rec["description"] = f"Add test for {cat} category"

            recommendations.append(rec)

    # For missing KB strategies, also add recommendations
    for strat in missing_strategies[:3]:
        recommendations.append({
            "category": "knowledge_base",
            "priority": "medium",
            "suggested_test": f"test_{strat['strategy_id']}",
            "description": f"Add test covering strategy: {strat['name']}",
            "from_signal": strat.get("signal", ""),
        })

    # 7. Summary
    total_covered = sum(info["covered"] for info in coverage_by_category.values())
    total_recommended = sum(info["recommended"] for info in coverage_by_category.values())
    total_gap = sum(info["gap"] for info in coverage_by_category.values())
    coverage_pct = round(
        total_covered / total_recommended * 100, 1,
    ) if total_recommended > 0 else 100.0

    summary = {
        "total_tests": len(test_descriptions),
        "categories_covered": sum(
            1 for info in coverage_by_category.values() if info["covered"] > 0
        ),
        "categories_total": len(coverage_by_category),
        "total_covered": total_covered,
        "total_recommended": total_recommended,
        "total_gap": total_gap,
        "coverage_percentage": min(coverage_pct, 100.0),
        "risk_areas_count": len(risk_areas),
        "critical_gaps": sum(1 for r in risk_areas if r["severity"] == "critical"),
    }

    result = {
        "coverage_by_category": coverage_by_category,
        "missing_strategies": missing_strategies,
        "risk_areas": risk_areas,
        "recommendations": recommendations,
        "summary": summary,
    }

    emit_event("evaluate_coverage", {
        "system_description": system_description[:120],
        "total_tests": len(test_descriptions),
        "coverage_pct": summary["coverage_percentage"],
        "risk_areas": len(risk_areas),
        "recommendations": len(recommendations),
    })

    return result
