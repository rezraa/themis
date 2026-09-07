# Copyright (c) 2026 Reza Malik. Licensed under the Apache License, Version 2.0.
"""MCP tool: get_signal_index

ONE read-only accessor over BOTH Shape-C signal indices, returning a NESTED typed
view — ``{strategy_signals: [{signal_id, signal_text, strategy_ids}],
pattern_signals: [{signal_id, signal_text, pattern_ids}]}`` — composed from the two
loader views (``kb.get_signal_index()`` over the test strategies and
``kb.get_pattern_signal_index()`` over the agent patterns). The SAME parameterized
engine serves both; one corpus per view.

The agent (LLM) recognises a problem's structural signals against the relevant labelled
surface in working memory — ``strategy_signals`` for plan_test_strategy /
evaluate_coverage's strategy reasoning, ``pattern_signals`` for agent-pattern
detection — then passes the matched ``signal_id``s to the retrieval engine
(``loader.hydrate`` for strategies, ``loader.hydrate_patterns`` for agent patterns).
This tool only exposes the two views; it performs no matching itself (matching is the
LLM's job / the frozen benchmark recognizer, never a fuzzy keyword pass in shipping
code). Zero-arg — it reaches no untrusted caller input, so the caller-boundary ceilings
(themis.tools._shared) do not apply to it.

WHY exactly ONE public top-level function (the reachability fix, council ae492280 /
m-5a5837da; root cause m-698d738c): Othrys' filename-keyed seed mints one graph tool
per file keyed by the file stem, so two co-located public functions collapse to a
single tool identity and the second is silently dropped. A single public function makes
that drop impossible by construction (parity with plan_test_strategy et al.).

WHY nested (not a flat per-entry type tag): S0's collision enumeration found FOUR signal
texts that appear in BOTH corpora ("long conversation sessions", "production reliability
requirement", "public-facing AI agent", "RAG-based agent with source documents"). A flat
text-only signal-id space would MERGE those across the views; nesting keeps each view a
separate map so they stay distinct (collision-safe by construction, m-5a5837da). The id
columns (``strategy_ids`` / ``pattern_ids``) already encode a signal's corpus, so nesting
needs no redundant per-entry tag, and the agent-strategy <-> agent-pattern twin is a
CROSS-LINK reference (each agent strategy's ``agent_pattern`` id) rather than a
duplication across the two views (Coeus DRY guard).
"""

from __future__ import annotations

from themis.tools._shared import get_knowledge


def get_signal_index(conn: object = None) -> dict:
    """Return both deterministic signal-index views in ONE nested composite.

    Args:
        conn: Optional Kuzu/LadybugDB connection. ``None`` -> JSON singleton loader;
            a connection -> the graph-backed loader (same engine, both modes and both
            corpora).

    Returns:
        ``{"strategy_signals": [{signal_id, signal_text, strategy_ids}, ...],
           "pattern_signals": [{signal_id, signal_text, pattern_ids}, ...]}`` — each view
        sorted by ``signal_id`` with sorted id-lists (``strategy_ids`` / ``pattern_ids``),
        so the composite serialises identically on every call.
    """
    kb = get_knowledge(conn)
    return {
        "strategy_signals": kb.get_signal_index(),
        "pattern_signals": kb.get_pattern_signal_index(),
    }
