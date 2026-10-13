# Copyright (c) 2026 Reza Malik. Licensed under the Apache License, Version 2.0.
"""MCP tool: get_signal_index

ONE read-only accessor over BOTH Shape-C signal indices, returning the COMPACT nested
recognition view — ``{strategy_signals: {strategy_id: {signal_id: signal_text}},
pattern_signals: {pattern_id: {signal_id: signal_text}}}`` — each group projected by
``loader.compact_signal_view`` from its own loader view (``kb.get_signal_index()`` over
the test strategies, ``kb.get_pattern_signal_index()`` over the agent patterns) with
that view's own owner-id key. The SAME parameterized engine serves both; one corpus per
group.

The agent (LLM) recognises a problem's structural signals against the relevant labelled
surface in working memory — ``strategy_signals`` for plan_test_strategy /
evaluate_coverage's strategy reasoning, ``pattern_signals`` for agent-pattern
detection — then passes the matched ``signal_id``s as ``matched_signal_ids`` to those
tools, which hydrate through the engine (``loader.hydrate`` for strategies,
``loader.hydrate_patterns`` for agent patterns). This tool only exposes the two views;
it performs no matching itself (matching is the LLM's job / the frozen benchmark
recognizer, never a fuzzy keyword pass in shipping code). Zero-arg — it reaches no
untrusted caller input, so the caller-boundary ceilings (themis.tools._shared) do not
apply to it.

WHY this compact inner shape (council 1e970338): the whole view is read in-model on
every recognition, so its size is the recognition cost. Keying signals by their owning
node carries exactly what the loader view carries (the view is recoverable from it)
with no per-entry field names and no per-signal id list. It is also a cacheable prefix:
owners and signals are emitted in sorted id order and the view is a pure function of
the corpus, so every call on one corpus serialises to the same bytes.

WHY exactly ONE public top-level function (the reachability fix, council ae492280 /
m-5a5837da; root cause m-698d738c): Othrys' filename-keyed seed mints one graph tool
per file keyed by the file stem, so two co-located public functions collapse to a
single tool identity and the second is silently dropped. A single public function makes
that drop impossible by construction (parity with plan_test_strategy et al.).

WHY nested (not a flat per-entry type tag): S0's collision enumeration found FOUR signal
texts that appear in BOTH corpora ("long conversation sessions", "production reliability
requirement", "public-facing AI agent", "RAG-based agent with source documents"). A flat
text-only signal-id space would MERGE those across the views; nesting keeps each view a
separate map so they stay distinct (collision-safe by construction, m-5a5837da). The
group a signal sits in already encodes its corpus, so nesting needs no redundant
per-entry tag, and the agent-strategy <-> agent-pattern twin is a
CROSS-LINK reference (each agent strategy's ``agent_pattern`` id) rather than a
duplication across the two views (Coeus DRY guard).
"""

from __future__ import annotations

from themis.knowledge.loader import compact_signal_view
from themis.tools._shared import get_knowledge


def get_signal_index(conn: object = None) -> dict:
    """Return both compact, byte-stable signal-index views in ONE nested composite.

    Args:
        conn: Optional Kuzu/LadybugDB connection. ``None`` -> JSON singleton loader;
            a connection -> the graph-backed loader (same engine, both modes and both
            corpora).

    Returns:
        ``{"strategy_signals": {strategy_id: {signal_id: signal_text}},
           "pattern_signals": {pattern_id: {signal_id: signal_text}}}`` — owners and
        each owner's signals in sorted id order. A signal owned by several nodes
        appears under each of them.
    """
    kb = get_knowledge(conn)
    return {
        "strategy_signals": compact_signal_view(kb.get_signal_index(), "strategy_ids"),
        "pattern_signals": compact_signal_view(kb.get_pattern_signal_index(), "pattern_ids"),
    }
