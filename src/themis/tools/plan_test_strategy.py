# Copyright (c) 2026 Reza Malik. Licensed under the Apache License, Version 2.0.
"""MCP tool: plan_test_strategy — wired onto the Shape-C retrieval engine.

Recommend testing strategies for the signals a caller recognised against
``get_signal_index``. The tool follows the cross-titan retrofit template
(retrieve -> gate -> reason over each node's OWN fields -> four-state envelope;
council 25d9a8ea / m-6ce2dcc3):

1. RETRIEVE strategies through one ``kb.hydrate`` call over the strategy-signal
   view — the proven four-state, fail-closed envelope; ``no_match``/``dangling``
   abstain to empty lists, never a husk. The corpus's own 226-signal vocabulary is
   the single source of truth (the legacy substring matcher over the decision-rules
   table was deleted at S5, once this tool and evaluate_coverage reached it through
   the hydrate path instead).
2. GATE the retrieved strategies through ``kb.filter_by_constraints`` — the ONE
   constraint gate, reading each strategy's OWN nested ``complexity``
   {setup, maintenance, execution} and ``compatible_frameworks`` (the excluded set
   survives as ``filtered_out`` with its reason).
3. REASON over each surviving strategy's OWN fields — real ``complexity``,
   ``compatible_frameworks``, ``applies_when``/``avoid_when``/``trade_offs`` (these
   are the strategy's own "why", so no separate rule-provenance block is emitted) —
   and detect agent testing patterns through a SECOND hydrate over the agent-pattern
   view (``kb.hydrate_patterns``), surfacing the rich corpus block (``test_approach``,
   ``example_test_case``, ``metrics``, ``severity``, ``adapters``).

The retrofit fixes two wrong-field reads the live path always defaulted:
``complexity`` was read as a phantom flat ``setup_complexity`` (always "medium"), and
top-level ``frameworks`` was read as a phantom ``frameworks`` key (always empty — the
real field is ``compatible_frameworks``). It also DELETES the hardcoded
agent-signal/agent-pattern island, whose 12 stub patterns shadowed the 60-signal
agent_patterns.json corpus and carried none of its fields; agent-pattern detection now
flows through the loader's real agent-pattern methods.

The two MCP-boundary params are truly required (no default), so the advertised
signature lists them in ``required`` and a missing one raises the native TypeError
that Othrys' ``_signature_error`` renders; unknown kwargs are still rejected loudly
(bound by test_tool_hardening.py). ``matched_signal_ids`` carries the matched SIGNAL
IDS the caller recognised against ``get_signal_index`` (problem-language -> sig-id,
the reachable path), not prose.

Firewall: imports only themis.* — never othrys.*/coeus.*/mnemos.*/theia.*.
"""

from __future__ import annotations

from typing import Any

from themis.knowledge.loader import DANGLING, NO_MATCH
from themis.tools._shared import (
    _MAX_MATCHED_SIGNALS,
    _bounded_constraints,
    coerce,
    emit_event,
    get_knowledge,
)


def _strategy_view(s: dict) -> dict:
    """Project a hydrated strategy onto the tool's output surface — OWN fields only.

    Reads each field the node genuinely carries: real nested ``complexity``
    (not a phantom flat ``setup_complexity``), ``compatible_frameworks`` (not a
    phantom ``frameworks`` key), and the ``applies_when``/``avoid_when``/
    ``trade_offs`` reasoning fields. Nested containers are copied to plain
    dict/list so the frozen singleton corpus is never aliased into the result.
    """
    return {
        "strategy_id": s.get("id", ""),
        "name": s.get("name", s.get("id", "")),
        "category": s.get("category", ""),
        "description": s.get("description", ""),
        "complexity": dict(s.get("complexity") or {}),
        "compatible_frameworks": list(s.get("compatible_frameworks") or []),
        "applies_when": list(s.get("applies_when") or []),
        "avoid_when": list(s.get("avoid_when") or []),
        "trade_offs": list(s.get("trade_offs") or []),
        "confidence": s.get("confidence", ""),
        "alternatives": list(s.get("alternatives") or []),
        "agent_pattern": s.get("agent_pattern", ""),
        "retrieval": dict(s.get("retrieval") or {}),
    }


def _agent_pattern_view(p: dict) -> dict:
    """Project a hydrated agent pattern onto the output surface — OWN corpus fields.

    Surfaces the rich agent_patterns.json block the deleted hardcoded island never
    carried: ``test_approach``, ``example_test_case``, ``metrics``, ``severity``,
    ``adapters``. Nested containers copied to plain dict/list.
    """
    return {
        "pattern_id": p.get("id", ""),
        "name": p.get("name", p.get("id", "")),
        "description": p.get("description", ""),
        "test_approach": p.get("test_approach", ""),
        "example_test_case": dict(p.get("example_test_case") or {}),
        "metrics": list(p.get("metrics") or []),
        "severity": p.get("severity", ""),
        "adapters": list(p.get("adapters") or []),
        "signals": list(p.get("signals") or []),
        "retrieval": dict(p.get("retrieval") or {}),
    }


def plan_test_strategy(
    system_description: Any,
    matched_signal_ids: Any,
    constraints: dict | None = None,
    k: int = 10,
    conn: object = None,
    **extra: Any,
) -> dict:
    """Recommend testing strategies for a caller's matched signal ids.

    Args:
        system_description: Description of what needs testing — context/telemetry
            only (retrieval is driven by ``matched_signal_ids``, not this text).
        matched_signal_ids: The matched SIGNAL IDS recognised against
            ``get_signal_index`` (e.g. ["sig-04591c9f637f", ...]). Required — a
            missing value raises rather than silently defaulting, since an empty
            signal set would mask a caller bug. Ids the index does not recognise are
            surfaced in ``unmatched_signals`` and the leg abstains, never a husk.
        constraints: Optional dict read by ``kb.filter_by_constraints`` — keys
            ``language``/``category``/``max_setup``/``max_maintenance``/
            ``max_execution``/``agent_testing_support``. Bounded at the boundary.
        k: Number of ranked strategies/patterns to retrieve (engine-clamped 1..50).
        conn: Kuzu/LadybugDB connection for graph mode, or None for JSON.

    Returns:
        Dict with ``recommended_strategies`` (each with its OWN
        complexity/compatible_frameworks/applies_when/avoid_when/trade_offs),
        ``frameworks`` (union of the recommended strategies' compatible_frameworks),
        ``alternatives`` (fanned-out neighbours), ``filtered_out``, the retrieval
        envelope (``retrieval_state``/``agent_pattern_state``/``unmatched_signals``/
        ``dangling``), and ``agent_patterns`` when the agent-pattern leg hydrates.
        Fail-closed: an abstaining leg contributes empty lists, never a husk.
    """
    # --- MCP-boundary arg hardening (contract bound by test_tool_hardening.py) ---
    # system_description and matched_signal_ids are truly required (no default), so
    # inspect.signature advertises them in `required` and a missing one raises the
    # native TypeError that Othrys' _signature_error renders. **extra stays only to
    # reject unknown kwargs loudly rather than silently dropping them.
    if extra:
        raise TypeError(
            "plan_test_strategy() got unexpected keyword argument(s): "
            + ", ".join(sorted(extra))
        )

    matched_signal_ids = coerce(matched_signal_ids, list, default=[])
    constraints = _bounded_constraints(coerce(constraints, dict, default={}))
    try:
        k = int(k)
    except (TypeError, ValueError):
        k = 10

    kb = get_knowledge(conn)
    # Named ceiling applied where the cost is incurred: bound the caller's id list
    # BEFORE it reaches hydrate (non-amplifying — the engine's _SEED_CAP bounds the
    # fan-out downstream of this).
    seed_ids = matched_signal_ids[:_MAX_MATCHED_SIGNALS]

    # 1. RETRIEVE strategies via the strategy-signal hydrate seam (four-state envelope).
    strat = kb.hydrate(seed_ids, k=k)

    recommended_strategies: list[dict[str, Any]] = []
    alternatives: list[dict[str, Any]] = []
    filtered_out: list[dict[str, Any]] = []
    frameworks: list[str] = []

    # Fail closed: recognised-but-empty (no_match) or unresolvable (dangling)
    # abstains structurally — no strategies, no frameworks, never a husk.
    if strat.state not in (NO_MATCH, DANGLING):
        # 2. GATE — the ONE constraint gate over each strategy's OWN complexity /
        #    compatible_frameworks; the excluded set survives with its reason.
        survivors, removed = kb.filter_by_constraints(list(strat.patterns), constraints)
        filtered_out = [
            {
                "strategy_id": r.get("id", ""),
                "name": r.get("name", r.get("id", "")),
                "reason": r.get("filter_reason", ""),
            }
            for r in removed
        ]

        # 3a. REASON — a directly-matched seed is a recommendation; a fanned-out
        #     neighbour (propagated-only) is an alternative. The retrieval envelope's
        #     ``seed`` flag is the split, so no arbitrary score threshold is invented.
        for s in survivors:
            view = _strategy_view(s)
            (recommended_strategies if view["retrieval"].get("seed") else alternatives).append(view)

        # 3b. frameworks — union of each recommended strategy's OWN compatible_frameworks
        #     (was always [] because the old read looked for a phantom ``frameworks`` key).
        seen_fw: set[str] = set()
        for view in recommended_strategies:
            for fw in view["compatible_frameworks"]:
                key = fw.lower()
                if key not in seen_fw:
                    seen_fw.add(key)
                    frameworks.append(fw)

    # 4. Agent-pattern detection via the pattern-signal hydrate seam (direct-vote-only,
    #    no fan-out, no fabricated neighbour). Independent of the strategy leg: a caller
    #    passing only pattern signals still gets patterns, and vice versa.
    pat = kb.hydrate_patterns(seed_ids, k=k)
    agent_patterns: list[dict[str, Any]] = []
    if pat.state not in (NO_MATCH, DANGLING):
        agent_patterns = [_agent_pattern_view(p) for p in pat.patterns]

    # 5. Envelope (fail-closed visibility). A signal id is unmatched OVERALL only when
    #    NEITHER view recognised it (intersection); dangling ids from either leg are
    #    integrity failures worth surfacing (union).
    result: dict[str, Any] = {
        "recommended_strategies": recommended_strategies,
        "frameworks": frameworks,
        "alternatives": alternatives,
        "filtered_out": filtered_out,
        "retrieval_state": strat.state,
        "agent_pattern_state": pat.state,
        "unmatched_signals": sorted(set(strat.unmatched_signals) & set(pat.unmatched_signals)),
        "dangling": sorted(set(strat.dangling) | set(pat.dangling)),
    }
    if agent_patterns:
        result["agent_patterns"] = agent_patterns

    emit_event("plan_test_strategy", {
        "system_description": system_description[:120] if isinstance(system_description, str) else "",
        "n_signals": len(matched_signal_ids),
        "retrieval_state": strat.state,
        "agent_pattern_state": pat.state,
        "strategies_count": len(recommended_strategies),
        "agent_patterns_count": len(agent_patterns),
        "filtered_out_count": len(filtered_out),
    })

    return result
