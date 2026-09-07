# Copyright (c) 2026 Reza Malik. Licensed under the Apache License, Version 2.0.
"""Shape-C two-view engine harness for themis-Gmetric (story-6c63a3bd, S2;
council 25d9a8ea / m-6ce2dcc3).

The S2 bar is measured by feeding the SAME frozen benchmark queries through the ported
Shape-C engine (``loader.hydrate`` over the strategy view + ``loader.hydrate_patterns``
over the agent-pattern view) and grading with ``grade.grade`` VERBATIM. The grader hands
a method ``prob["query"]``; hydrate needs matched *signal ids*. The bridge is a
RECOGNIZER — in production an LLM recognises a problem's signals against
``get_signal_index()`` in working memory; the benchmark cannot run an LLM
deterministically, so this module is its FROZEN, gold-blind stand-in (mirroring the
SHIPPED mnemos_engine_bench.py / theia_engine_bench.py by READING them, never importing
them — firewall: themis.* only).

Why a recognizer, and why the curated SHAPE (mnemos/theia parity, Theia S0-FIX lesson):
a purely lexical query-only recognizer cannot clear the problem-language strata — the
S-PL/P-PL paraphrases share few verbatim tokens with the corpus signal texts, and the
verbatim-query contract forbids reading the problem statement into the corpus. So
recognition reuses the S0-frozen, gold-blind ``SHAPE`` (imported from themis_recognizer,
the recogniser's working memory authored from the problem prose ALONE, never from the
answer key) and runs two deterministic legs over EACH view:

  1. OVERLAP — a signal whose text shares >= 2 stemmed content tokens with
     (query + SHAPE[pid]). This is how S-PL lands: the S2 fold put each decision rule's
     problem-idiom phrasing onto the strategy it recommends, so a paraphrase now overlaps
     a folded signal and hydrate reaches that strategy, whose OWN signals carry the gold.
  2. EXACT — a query string that verbatim IS a catalogued signal text (how the verbatim
     S-V / P-V registers land).

Recognition runs over BOTH views and routes per view: strategy-signal ids seed
``loader.hydrate`` (fans out over ``alternatives``); pattern-signal ids seed
``loader.hydrate_patterns`` (direct-vote-only, no edge). The two views' engine-ranked
reached nodes are combined ROUND-ROBIN (view-symmetric): neither view's fan-out score
scale can starve the other, so a rank-1 hit in either view lands near the top — the fix
for the collision-text problems where a strategy fan-out would otherwise bury the pattern
node. Each reached node contributes its OWN benchmark per-kind signal ids
(``themis_recognizer.build_vocabulary`` / ``sig_id``), first-seen — the same
recognition-vocabulary id space the frozen answer key and the pinned matcher baseline
use, so the comparison is apples-to-apples.

Firewall: imports only the sibling themis_recognizer (themis-only) + stdlib. Reads only
problems_blind + the loader's live index; NEVER reads gmetric_*.json (the answer key).
No live-DB access.
"""

from __future__ import annotations

import re
from collections import defaultdict

from themis_recognizer import SHAPE, build_vocabulary, sig_id  # noqa: F401  (themis-only)

# --------------------------------------------------------------------------- #
# Deterministic, gold-independent text normalisation (IR-standard). A faithful mirror
# of the mnemos/theia engine-bench tokenizer so the mountain grades on ONE normalisation.
# This lives in the TEST HARNESS (the LLM stand-in), never in shipping retrieval code:
# Themis's shipping engine does NO keyword matching; it takes matched signal ids as input
# (from the LLM in production, from this recognizer in the benchmark). So this token
# overlap is not the loader's "no fuzzy matching" doctrine's concern.
# --------------------------------------------------------------------------- #
_STOP = set(
    "a an the of to in for and or is are with be by on at from into over as you i "
    "my me can how what is do so each some any all more most only not that this "
    "these those it its their them then than we our your there many single every "
    "out back same much may must onto per keep given find".split())


def _stem(w: str) -> str:
    """Conservative plural-only normalisation (deterministic, gold-independent)."""
    if len(w) > 4 and w.endswith("s") and not w.endswith(("ss", "us", "is", "as", "os")):
        return w[:-1]
    return w


def _toks(s: str) -> set[str]:
    """Lowercase -> content tokens (non-alnum split, stop-word + length filter, stem)."""
    raw = [t for t in re.split(r"[^a-z0-9]+", s.lower()) if t and t not in _STOP and len(t) > 2]
    return {_stem(t) for t in raw}


def recognize_view(view: list[dict], query: list[str], shape: list[str]) -> list[str]:
    """Recognise matched signal ids for one problem against ONE signal-index view.

    Two deterministic, gold-blind legs: OVERLAP (>= 2 stemmed content tokens between
    (query + SHAPE) and the signal text) and EXACT (a query string that verbatim IS a
    catalogued signal text). Returns a sorted, de-duplicated list of the view's signal
    ids. Reads only its arguments — never the gold answer key.
    """
    q: set[str] = set()
    for qs in query:
        q |= _toks(qs)
    for ph in shape:
        q |= _toks(ph)
    text2id = {e["signal_text"].strip().lower(): e["signal_id"] for e in view}
    matched: set[str] = set()
    for e in view:
        if len(q & _toks(e["signal_text"])) >= 2:
            matched.add(e["signal_id"])
    for qs in query:
        hit = text2id.get(qs.strip().lower())
        if hit is not None:
            matched.add(hit)
    return sorted(matched)


def build_matches(loader) -> dict[str, dict[str, list[str]]]:
    """Recognise matched signal ids per view for every problem -> the auditable snapshot.

    ``{pid: {"strategy": [signal_id, ...], "pattern": [signal_id, ...]}}``. Pure function
    of (problems_blind, the loader's two live views, SHAPE). Used to emit the frozen
    snapshot and to prove live == frozen (gold-blind: never reads gmetric).
    """
    from themis_recognizer import _load_problems  # themis-only sibling
    strat_view = loader.get_signal_index()
    pat_view = loader.get_pattern_signal_index()
    out: dict[str, dict[str, list[str]]] = {}
    for p in _load_problems():
        shape = SHAPE.get(p["id"], [])
        out[p["id"]] = {
            "strategy": recognize_view(strat_view, p["query"], shape),
            "pattern": recognize_view(pat_view, p["query"], shape),
        }
    return out


# --------------------------------------------------------------------------- #
# reached node -> its OWN benchmark per-kind signal ids (file order). Derived from the
# ONE vocabulary definition (themis_recognizer.build_vocabulary), so gold ids and reached
# ids live in the same id space. Cached per loader identity.
# --------------------------------------------------------------------------- #
_SIG_BY_OWNER: dict[int, tuple[dict, dict]] = {}


def _sig_by_owner(loader):
    key = id(loader)
    cached = _SIG_BY_OWNER.get(key)
    if cached is None:
        vocab = build_vocabulary(loader)
        s: dict[str, list[str]] = defaultdict(list)
        for row in vocab["strategy"]:
            s[row["owner_id"]].append(row["signal_id"])
        p: dict[str, list[str]] = defaultdict(list)
        for row in vocab["pattern"]:
            p[row["owner_id"]].append(row["signal_id"])
        cached = (dict(s), dict(p))
        _SIG_BY_OWNER[key] = cached
    return cached


def _roundrobin(pattern_nodes: list[str], strategy_nodes: list[str]) -> list[tuple[str, str]]:
    """Interleave the two views' engine-ranked reached-node lists, view-symmetric.

    ``[(kind, node_id), ...]`` with kind in {"p", "s"}. Pattern-then-strategy within each
    round so a rank-1 pattern hit is never buried behind a strategy fan-out (the collision
    -text fix); the within-view order is the engine's own deterministic ranking.
    """
    order: list[tuple[str, str]] = []
    for i in range(max(len(pattern_nodes), len(strategy_nodes))):
        if i < len(pattern_nodes):
            order.append(("p", pattern_nodes[i]))
        if i < len(strategy_nodes):
            order.append(("s", strategy_nodes[i]))
    return order


def rank_engine(loader, query: list[str]) -> list[str]:
    """Map a frozen query -> ranked recognition-vocabulary signal ids via the two-view
    Shape-C engine. The ``(loader, query) -> ranked ids`` method_fn contract ``grade.grade``
    drives verbatim (the same shape the pinned matcher baseline was graded under).

    Recognises matched signal ids against the loader's LIVE two views, hydrates each
    (strategy view fans out over ``alternatives``; pattern view is direct-vote-only),
    combines the reached nodes round-robin, and emits each reached node's OWN benchmark
    signal ids first-seen. Empty recognition -> empty (an honest NO_MATCH, never a husk).
    """
    from themis_recognizer import _query_to_pid  # themis-only sibling
    pid = _query_to_pid().get(tuple(query))
    shape = SHAPE.get(pid, []) if pid else []

    ms = recognize_view(loader.get_signal_index(), query, shape)
    mp = recognize_view(loader.get_pattern_signal_index(), query, shape)
    strat_res = loader.hydrate(ms, k=10, fan_out=True)
    pat_res = loader.hydrate_patterns(mp, k=10)

    s_nodes = [p["id"] for p in strat_res.patterns]      # engine-ranked within view
    p_nodes = [p["id"] for p in pat_res.patterns]
    sig_by_strat, sig_by_pat = _sig_by_owner(loader)

    ranked: list[str] = []
    seen: set[str] = set()
    for kind, nid in _roundrobin(p_nodes, s_nodes):
        src = sig_by_pat if kind == "p" else sig_by_strat
        for sid in src.get(nid, []):
            if sid not in seen:
                seen.add(sid)
                ranked.append(sid)
    return ranked
