# Copyright (c) 2026 Reza Malik. Licensed under the Apache License, Version 2.0.
"""MCP tool: evaluate_coverage — wired onto the Shape-C retrieval engine.

Measure test-coverage gaps against the REACHABLE corpus: the strategies and agent
patterns actually recommended for the system's OWN signals, retrieved through the
S2 hydrate seams (``kb.hydrate`` / ``kb.hydrate_patterns``) and the four-state
fail-closed envelope — not against a hardcoded category rubric alone. The tool
follows the cross-titan retrofit template (retrieve -> reason over each node's OWN
fields -> four-state envelope; council 25d9a8ea / m-6ce2dcc3):

1. RETRIEVE the recommended strategies (``kb.hydrate`` over the strategy-signal view,
   fanning out over the corpus's ``alternatives`` edge) and the recommended agent
   patterns (``kb.hydrate_patterns``, direct-vote-only). ``no_match``/``dangling``
   abstain to empty recommended sets, never a husk.
2. REASON over each recommended node's OWN fields — a strategy's ``category`` and
   ``name``, an agent pattern's ``severity`` — to name the real corpus nodes a
   suite leaves uncovered: ``missing_strategies`` are recommended STRATEGY nodes no
   test covers; corpus ``risk_areas`` are recommended AGENT PATTERNS no test covers
   (carrying their own severity) plus rubric-gap categories annotated with the real
   strategies the corpus recommends for them.
3. SCORE against ``_DEFAULT_CATEGORIES`` demoted to WEIGHTS ONLY (recommended_min,
   priority) — the legitimate scoring lens over what a suite tested — while the
   corpus ``category`` supplies the CONTENT: a corpus category the rubric never
   held (e.g. "unit") now appears in ``coverage_by_category`` carrying its
   recommended real strategies.

The retrofit fixes the dead corpus reach: the pre-retrofit path read the phantom
``recommended_pattern`` key (the loader sets ``recommended_strategy``), so
``missing_strategies`` was ALWAYS [], and it reached the corpus only through the
legacy lossy substring matcher over the decision-rules table. It now retrieves through
the accessor's own 226-signal vocabulary; the legacy matcher was left at zero callers
here and at S3, and deleted at S5.

Firewall: imports only themis.* — never othrys.*/coeus.*/mnemos.*/theia.*.
"""

from __future__ import annotations

from typing import Any

from themis.knowledge.loader import DANGLING, NO_MATCH
from themis.tools._shared import (
    _MAX_MATCHED_SIGNALS,
    coerce,
    emit_event,
    get_knowledge,
)

# ---------------------------------------------------------------------------
# Scoring weights — the general coverage-dimension rubric, DEMOTED to weights only
# (recommended_min + priority), no longer the sole content source. The corpus
# `category` field is the content source (see the module docstring); this table is
# the legitimate scoring lens over what a suite already tested. Each entry's
# ``description`` labels the rubric dimension it weighs.
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

# Category aliases — normalise a raw category (a test's declared category OR a corpus
# strategy's `category`) into a rubric weight key where the corpus taxonomy and the
# rubric taxonomy name the same dimension (e.g. corpus "security" weighs as "safety",
# corpus "load" as "performance"). A corpus category with no rubric twin (unit,
# integration, e2e, ...) passes through unchanged and supplies its own content.
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

# Weight for a corpus category the rubric does not define (its content comes from the
# corpus; only the scoring weight defaults here). Auditable integers, not tuned.
_CORPUS_CATEGORY_MIN = 1
_CORPUS_CATEGORY_PRIORITY = "high"

_PRIORITY_RANK = {"critical": 3, "high": 2, "medium": 1, "low": 0}


def _normalise_category(raw: str) -> str:
    """Map a raw category string to its rubric weight key, else pass it through."""
    lower = raw.lower().strip().replace(" ", "_")
    return _CATEGORY_ALIASES.get(lower, lower)


def _infer_category(test_desc: dict[str, Any]) -> str:
    """Infer a coverage category from a test description's fields.

    An explicit ``category`` is normalised (so a test tagged "unit"/"security" lands
    in the matching corpus/rubric bucket); otherwise the category is inferred from the
    name/what_it_tests prose by keyword overlap, defaulting to ``functional``.
    """
    cat = test_desc.get("category", "")
    if cat:
        return _normalise_category(cat)

    name = test_desc.get("name", "").lower()
    what = test_desc.get("what_it_tests", "").lower()
    combined = f"{name} {what}"

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


# Testing-vocabulary tokens carry no coverage signal: every test is named "test_*"
# and describes a "case", so matching them would mark every recommended node covered.
_GENERIC_TOKENS = frozenset({"test", "tests", "testing", "case", "cases", "strategy", "pattern"})


def _tokens(text: str) -> list[str]:
    """Distinctive (>3 char, non-generic) tokens of a corpus node, for coverage matching."""
    return [
        t for t in text.lower().replace("-", " ").replace("_", " ").split()
        if len(t) > 3 and t not in _GENERIC_TOKENS
    ]


def _covered_by_tests(node: dict, all_test_text: str) -> bool:
    """Does any existing test's text mention a distinctive token of *node* (id + name)?

    The name-token heuristic the pre-retrofit tool used, applied to REAL recommended
    corpus nodes (its target was always empty before), and hardened against the
    generic testing vocabulary that would otherwise mark every node covered.
    """
    text = f"{node.get('id', '')} {node.get('name', '')}"
    return any(tok in all_test_text for tok in _tokens(text))


# ---------------------------------------------------------------------------
# Main tool
# ---------------------------------------------------------------------------

def evaluate_coverage(
    test_descriptions: list[dict],
    system_description: str,
    structural_signals: list[str],
    k: int = 10,
    conn: object = None,
) -> dict:
    """Measure test-coverage gaps against the reachable corpus.

    Args:
        test_descriptions: List of dicts describing existing tests, each with
            ``name``, ``category`` (normalised), and ``what_it_tests``.
        system_description: Description of the system under test — context/telemetry
            only (the reachable corpus is driven by ``structural_signals``).
        structural_signals: The matched SIGNAL IDS the caller recognised against
            ``get_signal_index`` (e.g. ["sig-04591c9f637f", ...]), not prose. An
            explicit empty list is honest "no signals recognised" — the rubric
            scoring lens still runs over the provided tests; the corpus contributes
            nothing (fail-closed), never a fabricated node.
        k: Number of ranked strategies/patterns to retrieve (engine-clamped 1..50).
        conn: Kuzu/LadybugDB connection for graph mode, or None for JSON.

    Returns:
        Dict with ``coverage_by_category`` (rubric weights + the corpus strategies
        recommended per category), ``missing_strategies`` (recommended corpus
        strategy nodes no test covers), ``risk_areas`` (recommended agent-pattern
        nodes no test covers, carrying their own severity, plus rubric-gap categories
        naming their recommended strategies), ``recommendations``, ``summary``, and
        the retrieval envelope (``retrieval_state``/``agent_pattern_state``/
        ``unmatched_signals``/``dangling``). Fail-closed: an abstaining leg
        contributes no corpus content, never a husk.
    """
    test_descriptions = coerce(test_descriptions, list) or []
    matched_signal_ids = coerce(structural_signals, list) or []
    try:
        k = int(k)
    except (TypeError, ValueError):
        k = 10

    kb = get_knowledge(conn)
    # Named ceiling applied where the cost is incurred: bound the caller's id list
    # BEFORE hydrate (non-amplifying — the engine's _SEED_CAP bounds fan-out below).
    seed_ids = matched_signal_ids[:_MAX_MATCHED_SIGNALS]

    # 1. RETRIEVE the reachable corpus through the four-state fail-closed envelope.
    #    A recognised-but-empty (no_match) or unresolvable (dangling) leg abstains to
    #    an empty recommended set — no corpus content, never the nearest husk.
    strat = kb.hydrate(seed_ids, k=k)
    pat = kb.hydrate_patterns(seed_ids, k=k)
    recommended_strategies = list(strat.patterns) if strat.state not in (NO_MATCH, DANGLING) else []
    recommended_patterns = list(pat.patterns) if pat.state not in (NO_MATCH, DANGLING) else []

    # 2. Categorise existing tests (the "what IS tested" side, rubric taxonomy).
    category_counts: dict[str, int] = {}
    categorised_tests: dict[str, list[str]] = {}
    for td in test_descriptions:
        cat = _infer_category(td)
        category_counts[cat] = category_counts.get(cat, 0) + 1
        categorised_tests.setdefault(cat, []).append(td.get("name", "unnamed"))

    all_test_text = " ".join(
        {td.get("name", "").lower() for td in test_descriptions}
        | {td.get("what_it_tests", "").lower() for td in test_descriptions}
    )

    # 3. Map the reachable corpus's recommended strategies onto categories — the CONTENT
    #    the corpus supplies. Each strategy's OWN `category` is normalised onto the
    #    scoring axis; strategies with no rubric twin (unit, integration, ...) bring
    #    their own category in.
    strategies_by_category: dict[str, list[dict[str, str]]] = {}
    for s in recommended_strategies:
        cat = _normalise_category(s.get("category", "")) or "uncategorised"
        strategies_by_category.setdefault(cat, []).append(
            {"strategy_id": s.get("id", ""), "name": s.get("name", s.get("id", ""))}
        )

    # 4. coverage_by_category — the union of the rubric weight categories, the existing
    #    tests' categories, and the corpus's recommended-strategy categories. Weights
    #    (recommended_min, priority) come from _DEFAULT_CATEGORIES; a corpus-only
    #    category takes the corpus default weight. `recommended_strategies` is the
    #    corpus content per category (real nodes), demoting the rubric from monopoly.
    coverage_by_category: dict[str, dict[str, Any]] = {}
    # Sorted so the result serialises deterministically regardless of set/hash order.
    all_categories = sorted(set(_DEFAULT_CATEGORIES) | set(category_counts) | set(strategies_by_category))
    for cat in all_categories:
        weight = _DEFAULT_CATEGORIES.get(cat)
        in_rubric = weight is not None
        has_corpus = cat in strategies_by_category
        covered = category_counts.get(cat, 0)
        recommended = weight["recommended_min"] if in_rubric else _CORPUS_CATEGORY_MIN
        coverage_by_category[cat] = {
            "description": weight["description"] if in_rubric
                else f"Corpus-recommended category: {cat}",
            "covered": covered,
            "recommended": recommended,
            "gap": max(0, recommended - covered),
            "priority": weight["priority"] if in_rubric else _CORPUS_CATEGORY_PRIORITY,
            "tests": categorised_tests.get(cat, []),
            "recommended_strategies": strategies_by_category.get(cat, []),
            "source": "both" if (in_rubric and has_corpus)
                else "corpus" if has_corpus else "rubric",
        }

    # 5. missing_strategies — recommended corpus STRATEGY nodes no existing test covers
    #    (was ALWAYS [] because the old read looked for a phantom `recommended_pattern`
    #    key the loader never sets). Each names a real corpus node with its own category.
    missing_strategies: list[dict[str, Any]] = []
    for s in recommended_strategies:
        name = s.get("name", s.get("id", ""))
        if _covered_by_tests(s, all_test_text):
            continue
        missing_strategies.append({
            "strategy_id": s.get("id", ""),
            "name": name,
            "category": s.get("category", ""),
            "reason": "recommended for the system's signals but not covered by any test",
            "retrieval": dict(s.get("retrieval") or {}),
        })

    # 6. risk_areas — real corpus nodes first (fail-closed: only when a leg hydrated):
    #    (a) recommended AGENT PATTERNS no test covers, carrying their OWN severity;
    #    (b) coverage_by_category gaps (the weights lens), each naming the real
    #    strategies the corpus recommends for that category. Sorted by severity then gap.
    risk_areas: list[dict[str, Any]] = []
    for p in recommended_patterns:
        name = p.get("name", p.get("id", ""))
        if _covered_by_tests(p, all_test_text):
            continue
        severity = p.get("severity", "medium")
        risk_areas.append({
            "node_kind": "agent_pattern",
            "node_id": p.get("id", ""),
            "name": name,
            "severity": severity,
            "priority": severity,
            "gap": 1,
            "reason": "recommended agent pattern not covered by any test",
        })

    for cat, info in coverage_by_category.items():
        if info["gap"] <= 0:
            continue
        priority = info["priority"]
        severity = ("critical" if priority == "critical" and info["gap"] >= 2
                    else "high" if priority in ("critical", "high")
                    else "medium")
        risk_areas.append({
            "node_kind": "category",
            "category": cat,
            "description": info["description"],
            "gap": info["gap"],
            "priority": priority,
            "severity": severity,
            "recommended_strategies": info["recommended_strategies"],
        })

    risk_areas.sort(key=lambda r: (-_PRIORITY_RANK.get(r["severity"], 0), -r.get("gap", 0)))

    # 7. recommendations — corpus-sourced first (name real nodes), then a generic
    #    fallback for a pure-rubric gap the corpus recommended nothing for.
    recommendations: list[dict[str, Any]] = []
    for strat_ref in missing_strategies[:5]:
        recommendations.append({
            "category": _normalise_category(strat_ref["category"]) or "uncategorised",
            "priority": "medium",
            "suggested_test": f"test_{strat_ref['strategy_id']}",
            "description": f"Add a test exercising strategy: {strat_ref['name']}",
            "from_strategy": strat_ref["strategy_id"],
        })
    for risk in risk_areas:
        if risk["node_kind"] != "agent_pattern":
            continue
        recommendations.append({
            "category": "agent_pattern",
            "priority": risk["priority"],
            "suggested_test": f"test_{risk['node_id']}",
            "description": f"Add an agent-pattern test: {risk['name']}",
            "from_pattern": risk["node_id"],
        })
    for risk in risk_areas:
        if risk["node_kind"] != "category" or risk.get("recommended_strategies"):
            continue
        cat = risk["category"]
        recommendations.append({
            "category": cat,
            "priority": risk["priority"],
            "suggested_test": f"test_{cat}_coverage",
            "description": f"Add {risk['gap']} more test(s) for the {cat} dimension "
                           f"({risk['description']})",
        })

    # 8. Summary.
    total_covered = sum(info["covered"] for info in coverage_by_category.values())
    total_recommended = sum(info["recommended"] for info in coverage_by_category.values())
    total_gap = sum(info["gap"] for info in coverage_by_category.values())
    coverage_pct = round(total_covered / total_recommended * 100, 1) if total_recommended > 0 else 100.0

    summary = {
        "total_tests": len(test_descriptions),
        "categories_covered": sum(1 for info in coverage_by_category.values() if info["covered"] > 0),
        "categories_total": len(coverage_by_category),
        "total_covered": total_covered,
        "total_recommended": total_recommended,
        "total_gap": total_gap,
        "coverage_percentage": min(coverage_pct, 100.0),
        "reachable_strategies": len(recommended_strategies),
        "reachable_agent_patterns": len(recommended_patterns),
        "missing_strategies_count": len(missing_strategies),
        "risk_areas_count": len(risk_areas),
        "critical_gaps": sum(1 for r in risk_areas if r["severity"] == "critical"),
    }

    result = {
        "coverage_by_category": coverage_by_category,
        "missing_strategies": missing_strategies,
        "risk_areas": risk_areas,
        "recommendations": recommendations,
        "summary": summary,
        "retrieval_state": strat.state,
        "agent_pattern_state": pat.state,
        "unmatched_signals": sorted(set(strat.unmatched_signals) & set(pat.unmatched_signals)),
        "dangling": sorted(set(strat.dangling) | set(pat.dangling)),
    }

    emit_event("evaluate_coverage", {
        "system_description": system_description[:120] if isinstance(system_description, str) else "",
        "total_tests": len(test_descriptions),
        "coverage_pct": summary["coverage_percentage"],
        "retrieval_state": strat.state,
        "agent_pattern_state": pat.state,
        "reachable_strategies": len(recommended_strategies),
        "missing_strategies": len(missing_strategies),
        "risk_areas": len(risk_areas),
        "recommendations": len(recommendations),
    })

    return result
