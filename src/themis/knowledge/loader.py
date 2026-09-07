# Copyright (c) 2026 Reza Malik. Licensed under the Apache License, Version 2.0.
"""Knowledge loader for Themis.

Loads test_strategies.json, agent_patterns.json, and frameworks.json and provides
pure retrieval, signal-index hydrate over the corpus's own ``structural_signals``,
and constraint filtering. (The legacy decision-rules table is no longer loaded: the
corpus's own signals are the single source of truth; the substring matcher was deleted at S5.)

No fuzzy keyword matching.  No tokenization.  No Jaccard scoring.
"""

from __future__ import annotations

import hashlib
import heapq
import json
from dataclasses import dataclass, field
from pathlib import Path

_KNOWLEDGE_DIR = Path(__file__).parent

# ---------------------------------------------------------------------------
# Complexity / execution speed ranking — lower index = faster / lighter.
# ---------------------------------------------------------------------------
_SETUP_RANK: dict[str, int] = {"low": 0, "medium": 1, "high": 2}
_MAINTENANCE_RANK: dict[str, int] = {"low": 0, "medium": 1, "high": 2}
_EXECUTION_RANK: dict[str, int] = {"fast": 0, "medium": 1, "slow": 2}


# ==========================================================================
# Shape-C retrieval engine — the signal-index hydrate path
# (problem-language signals -> test strategy), a JUSTIFIED MIRROR of the SHIPPED
# mnemos.knowledge.loader / coeus.knowledge.loader / theia.knowledge.loader
# ``_SignalEngine`` (council 25d9a8ea / m-6ce2dcc3; Shape-C standard m-55f6d4da).
# Themis runs standalone: its runtime code MUST NOT import
# othrys.*/coeus.*/mnemos.*/theia.* (the titan-decoupling firewall,
# feedback_titan_decoupling_no_othrys_import); the mirror is kept faithful by a
# semantic-parity drift test (tests/test_firewall.py). Adapted for the Themis
# corpus: the index source is each STRATEGY's ``structural_signals`` field (plural);
# the fan-out edge is ``alternatives``
# (already materialized, 47/47 non-empty, so hydrate fans out for real at S1); and
# the node index is a FLAT ``id -> strategy`` map (the Coeus/Theia shape, no
# ``(structure_id, pattern)`` tuple).
#
# The engine is PARAMETERIZED over a ``_NamedIndex`` seam — (index source, signal
# field, edge field) — so the SECOND named index over ``agent_patterns`` (S2) REUSES
# every primitive below (ceilings, floor, state vocab, ``_signal_id``,
# ``RetrievalResult``, ``deep_freeze``, the facet gate) with ZERO duplicated engine
# code. Both indices are wired: the strategy index fans out over ``alternatives``; the
# agent-pattern index is edgeless (direct-vote-only). ``tools/get_signal_index.py``
# composes the two loader views into the nested {strategy_signals, pattern_signals}.
#
# Themis-specific fail-closed addition (Hyperion husk-guard AC): the ``_NamedIndex``
# carries a ``required_fields`` axis, and :meth:`_SignalEngine._resolve_node`
# treats a node missing any of them as unresolved — a FIELD-SHORT node (a husk,
# e.g. the ``{id, name}`` stub the legacy accessor fabricates) resolves to DANGLING,
# never a silently-defaulted husk. The reference engines have no such axis; adding
# it does not move the shared primitives or the output contract the drift test
# asserts (a genuine node passes the guard and the contract is unchanged).
# ==========================================================================
#
# The four-state retrieval envelope is the single output contract. Every
# retrieval resolves to exactly one state, and abstention is a structural field
# rather than an empty list narrated as an answer (fail closed, never a husk).
HIT = "hit"                        # >=1 strategy hydrated at/above the confidence floor
LOW_CONFIDENCE = "low_confidence"  # strategies hydrated, best below the confidence floor
NO_MATCH = "no_match"              # signals recognised but none map to a corpus strategy
DANGLING = "dangling"              # signals map only to ids absent/husk in the corpus

# Two named ceilings bound the fan-out's agency, applied where cost is incurred:
_SEED_CAP: int = 64    # max seed strategies admitted to fan-out (bound BEFORE expansion)
_TOPK_CAP: int = 50    # hard ceiling on hydrated results (bound AFTER expansion)

# A hit needs at least this many corroborating votes (direct + propagated); a
# lone single vote is surfaced but flagged low_confidence. Auditable integer,
# not a tuned score.
_CONFIDENCE_FLOOR: int = 2


def _signal_id(text: str) -> str:
    """Deterministic, byte-reproducible id for a signal's text.

    A stable content hash so the corpus-derived index recomputes identically
    across processes (independent of PYTHONHASHSEED) and the LLM/harness can
    refer to a signal by a short id.
    """
    return "sig-" + hashlib.sha1(text.strip().encode("utf-8")).hexdigest()[:12]


@dataclass(frozen=True)
class RetrievalResult:
    """The single retrieval output contract (see the four states above).

    ``patterns`` is the ranked, hydrated result (empty for the abstention
    states — the field name is kept ``patterns`` for cross-titan envelope parity;
    the nodes are Themis test strategies). ``votes`` is the transparent, auditable
    tally used for ranking (strategy_id -> integer vote count). ``dangling``
    surfaces any referenced strategy id that did not resolve to a genuine corpus
    node — an integrity failure is reported, never masked by a husk.
    ``unmatched_signals`` records matched signal ids the index did not recognise.
    """

    state: str
    patterns: list[dict] = field(default_factory=list)
    votes: dict[str, int] = field(default_factory=dict)
    dangling: list[str] = field(default_factory=list)
    unmatched_signals: list[str] = field(default_factory=list)
    reason: str = ""


class _FrozenDict(dict):
    """A read-only ``dict``: refuses in-place mutation, serialises as a plain dict.

    Hydrated strategies are deep-frozen through this type so a caller cannot corrupt
    the shared singleton corpus by mutating a returned node (the shallow-copy
    shared-reference hazard: ``{**node}`` copies the top dict but aliases its nested
    lists). It subclasses ``dict`` so ``json.dumps`` and ``["key"]`` reads work
    unchanged; only the mutators are sealed.
    """

    __slots__ = ()

    def _readonly(self, *_a: object, **_k: object) -> None:
        raise TypeError("hydrated strategy is read-only")

    __setitem__ = __delitem__ = clear = pop = popitem = setdefault = update = _readonly


def deep_freeze(obj: object) -> object:
    """Recursively copy *obj* into an immutable, JSON-serialisable structure.

    Dicts become :class:`_FrozenDict`, lists/tuples become tuples, scalars pass
    through. The copy severs every shared reference to the source, so this both
    fixes the shared-ref corruption hazard and makes the result tamper-proof.
    """
    if isinstance(obj, dict):
        return _FrozenDict({k: deep_freeze(v) for k, v in obj.items()})
    if isinstance(obj, (list, tuple)):
        return tuple(deep_freeze(v) for v in obj)
    return obj


def _parse_team_range(token: object) -> tuple[float, float] | None:
    """Parse a ``team_size`` token (``"1-5"``, ``"50+"``, ``"3"``) into ``(lo, hi)``.

    Pure string arithmetic — no regex, no eval on caller input. Returns ``None``
    for anything unparseable so the gate can fail OPEN (never demote on a token it
    cannot read). Ported from the shipped mirror as part of the facet gate; DORMANT
    on the Themis strategy corpus (no strategy carries facet dicts), but kept
    faithful so the semantic-parity drift test holds and the S3-S5 tool retrofits
    have the primitive ready.
    """
    s = str(token).strip()
    if not s:
        return None
    try:
        if s.endswith("+"):
            return (int(s[:-1]), float("inf"))
        if "-" in s:
            lo, hi = s.split("-", 1)
            return (int(lo), int(hi))
        n = int(s)
        return (n, n)
    except (ValueError, TypeError):
        return None


def facet_matches(facet: dict, constraints: dict) -> bool:
    """Does one structured facet hold under the caller's *constraints*?

    The single facet-matching predicate (one source of truth, not one copy per
    reader). A facet is an AND of conditions; it matches only when the constraints
    confirm *every* key: ``team_size`` by numeric range overlap, every other key by
    categorical exact match (case/whitespace-normalised, never substring). Pure
    comparison — no ``eval``/regex on caller input; an unspecified or unreadable
    key yields ``False`` (fail open, never demote on unconfirmed input). Ported
    from the shipped mirror; DORMANT on the Themis strategy corpus (facet gate
    ready for S3-S5).
    """
    if not isinstance(facet, dict) or not facet:
        return False
    for key, fval in facet.items():
        cval = constraints.get(key)
        if cval is None:
            return False
        if key == "team_size":
            fr, cr = _parse_team_range(fval), _parse_team_range(cval)
            if fr is None or cr is None:
                return False
            if not (fr[0] <= cr[1] and cr[0] <= fr[1]):
                return False
        elif str(cval).strip().lower() != str(fval).strip().lower():
            return False
    return True


def split_conditions(items: list | None) -> tuple[list[str], list[dict]]:
    """Partition an ``applies_when``/``avoid_when`` list into its two kinds.

    These lists mix free-text condition strings (for LLM recognition) and
    structured facet dicts (for deterministic gating). Any reader dispatches on
    element type through this one helper. Single pass; tolerates ``None``. Returns
    ``(text_conditions, facet_constraints)``. Ported from the shipped mirror; on
    the Themis strategy corpus the facet half is always empty (DORMANT).
    """
    texts: list[str] = []
    facets: list[dict] = []
    for item in items or []:
        (facets if isinstance(item, dict) else texts).append(item)
    return texts, facets


def is_gated(node: dict, constraints: dict) -> bool:
    """Is *node* gated by its OWN ``avoid_when`` facets under *constraints*?

    Reasoning over the node's own field, not a hardcoded detector. Ported from the
    shipped mirror as the deterministic facet gate; DORMANT on the Themis strategy
    corpus (no strategy carries an ``avoid_when`` facet dict), so it always returns
    ``False`` here. The live constraint gate on Themis is
    :meth:`KnowledgeLoader.filter_by_constraints`.
    """
    if not constraints:
        return False
    _, facets = split_conditions(node.get("avoid_when"))
    return any(facet_matches(f, constraints) for f in facets)


@dataclass
class _NamedIndex:
    """Descriptor for ONE signal-index corpus the parameterized engine serves.

    The three behavioural axes the council named — (index source, signal field,
    edge field) — are ``node_index`` / ``signal_field`` / ``edge_field``.
    ``id_field`` labels the public view's id-list column for THIS corpus
    (``strategy_ids`` at S1; ``pattern_ids`` for S2's second index); it rides with
    the index source as a presentation facet, NOT a fourth behavioural axis — the
    ceilings, floor, state vocabulary, ranking and ``_signal_id`` are identical
    across corpora, which is exactly what the drift test asserts. ``required_fields``
    is the Themis husk guard (Hyperion fail-closed AC): the fields a genuine,
    tool-reasoned node must carry; a resolved node missing any is treated as a husk
    -> DANGLING (see :meth:`_SignalEngine._resolve_node`). ``name`` identifies the
    corpus. ``signal_index`` (signal_id -> entry) is populated by
    :meth:`_SignalEngine._build_signal_index`.
    """

    name: str
    node_index: dict[str, dict]
    signal_field: str
    edge_field: str
    id_field: str
    required_fields: tuple[str, ...] = ()
    signal_index: dict[str, dict] = field(default_factory=dict)


class _SignalEngine:
    """The Shape-C signal-index retrieval engine — inherited by BOTH loaders and
    PARAMETERIZED over a :class:`_NamedIndex` so one copy serves every corpus.

    :class:`KnowledgeLoader` (JSON) and ``GraphKnowledgeLoader`` (Kuzu, via
    subclassing — Themis's graph loader delegates its read path to the JSON parent,
    so it inherits this engine unchanged) build ``self._strategy_signal_index`` in
    ``__init__`` and expose the S1-wired zero-/one-arg public bindings that delegate
    here. Every primitive below reads only its ``_NamedIndex`` argument, so there is
    exactly ONE copy of the engine — no duplicate engine code across the two loaders,
    and none across the strategy index and S2's future agent_patterns index.
    """

    # ------------------------------------------------------------------
    # Index build (called from the loader's __init__, once per _NamedIndex)
    # ------------------------------------------------------------------

    def _build_signal_index(self, index: _NamedIndex) -> None:
        """Build ``index.signal_index`` from each node's ``index.signal_field``.

        Derived deterministically so the view is byte-reproducible (ids are
        content hashes; id-lists sorted). Fails CLOSED at load on a hash collision
        between two distinct signal texts — a 48-bit clash would silently merge
        two signals, so we refuse to serve a corrupted index rather than mask it.
        """
        index.signal_index = {}
        for node in index.node_index.values():
            nid = node["id"]
            for raw in node.get(index.signal_field, []):
                text = raw.strip()
                if not text:
                    continue
                sid = _signal_id(text)
                entry = index.signal_index.get(sid)
                if entry is None:
                    index.signal_index[sid] = {
                        "signal_id": sid,
                        "signal_text": text,
                        index.id_field: [nid],
                    }
                elif entry["signal_text"] != text:
                    raise ValueError(
                        f"signal_id collision {sid}: "
                        f"{text!r} vs {entry['signal_text']!r}"
                    )
                elif nid not in entry[index.id_field]:
                    entry[index.id_field].append(nid)
        for entry in index.signal_index.values():
            entry[index.id_field].sort()

    # ------------------------------------------------------------------
    # Node-id resolution (retrieval engine)
    # ------------------------------------------------------------------

    def _lookup_node(self, index: _NamedIndex, node_id: str) -> dict | None:
        """Resolve a node id to its stored dict by existence only, fail closed.

        Returns the real stored dict or ``None`` — never a synthesised ``{id, name}``
        husk. The mirror-faithful resolver: the drift test asserts this contract.
        The Themis husk guard layers on top in :meth:`_resolve_node`.
        """
        return index.node_index.get(node_id)

    def _resolve_node(self, index: _NamedIndex, node_id: str) -> dict | None:
        """Resolve to a GENUINE node, fail closed on absent OR field-short (husk).

        The Themis husk guard (Hyperion fail-closed AC): a node present in the index
        but missing a field a tool will reason over (``index.required_fields``) is a
        husk — the ``{id, name}`` stub the legacy accessor fabricates is the canonical
        case. It is treated as unresolved so hydrate records it as ``dangling`` and
        never emits it as a silently-defaulted husk. S1 seeds ``required_fields`` with
        the strategy corpus's genuine-node marker (``structural_signals`` + ``category``);
        the S3/S4 tool retrofits may tighten it to the exact field set their body reads.
        """
        node = self._lookup_node(index, node_id)
        if node is None:
            return None
        if any(not node.get(f) for f in index.required_fields):
            return None
        return node

    # ------------------------------------------------------------------
    # Signal-index retrieval engine (problem-language -> node)
    # ------------------------------------------------------------------

    def _signal_index_view(self, index: _NamedIndex) -> list[dict]:
        """Return the deterministic, byte-reproducible signal index view.

        Each entry is ``{signal_id, signal_text, <index.id_field>}``; the LLM
        recognises a problem's signals against this view at runtime and passes the
        matched signal ids to :meth:`_hydrate`. Sorted by ``signal_id`` with sorted
        id-lists so two builds serialise identically.
        """
        return [
            {
                "signal_id": e["signal_id"],
                "signal_text": e["signal_text"],
                index.id_field: list(e[index.id_field]),
            }
            for e in sorted(index.signal_index.values(), key=lambda e: e["signal_id"])
        ]

    def _signal_ids_for(self, index: _NamedIndex, node_id: str) -> list[str]:
        """Return the signal ids of *node_id*'s OWN signals.

        The seed-from-node entry point: a tool that already HOLDS a known node id
        recovers that node's own signal ids from the built index — exactly the ids
        :meth:`_hydrate` recognises — and seeds retrieval with them, so the fan-out
        expands over the node's edge without a caller-supplied recognition step.
        Reads only ``index.signal_index`` (the one source of truth for text ->
        signal id), so the JSON and graph loaders derive the IDENTICAL seed; sorted
        for a deterministic, byte-reproducible order. An unknown or signal-less id
        yields ``[]`` (the caller then hydrates to a fail-closed ``no_match``),
        never a fabricated seed.
        """
        return sorted(
            sid for sid, entry in index.signal_index.items()
            if node_id in entry[index.id_field]
        )

    def _hydrate(
        self,
        index: _NamedIndex,
        matched_signal_ids: list[str],
        k: int = 10,
        fan_out: bool = True,
    ) -> RetrievalResult:
        """Hydrate matched signals into ranked nodes, in the four-state envelope.

        End-to-end entry point a harness drives given matched signal ids:

        * maps each signal id -> its owning node(s), tallying a direct vote per
          signal (a seed's weight = number of matched signals mapping to it);
        * one-hop fan-out over ``index.edge_field`` from the capped seed set,
          propagating each seed's weight to its neighbours (when ``fan_out``);
        * selects the top-``k`` via a size-k heap (``heapq.nlargest``, O(n log k))
          over a two-tier composite key: direct-vote tier (a directly-matched seed
          outranks every propagated-only neighbour), then the pre-fan-out
          direct-vote count within the seed tier (accumulated vote score for
          propagated-only neighbours), then node id ascending — deterministic
          throughout.

        Every node is resolved through :meth:`_resolve_node` (the husk guard), so a
        field-short/absent seed does not fan out and a field-short/absent winner is
        recorded ``dangling`` rather than emitted — fail closed, never a husk.
        Bounded by two ceilings: ``_SEED_CAP`` before fan-out and ``_TOPK_CAP``
        after. Votes are transparent integer counts, never a tuned score.
        """
        k = min(max(int(k), 1), _TOPK_CAP)

        # 1. Direct hydration: matched signal -> seed node(s), one vote each.
        unmatched: list[str] = []
        direct_votes: dict[str, int] = {}
        for sid in matched_signal_ids or []:
            entry = index.signal_index.get(sid)
            if entry is None:
                unmatched.append(sid)
                continue
            for nid in entry[index.id_field]:
                direct_votes[nid] = direct_votes.get(nid, 0) + 1

        # Empty leg: recognised signals that hydrate to nothing -> abstain.
        if not direct_votes:
            return RetrievalResult(
                state=NO_MATCH,
                unmatched_signals=sorted(set(unmatched)),
                reason="no matched signal maps to a corpus strategy",
            )

        # 2. Seed cap BEFORE fan-out: rank seeds (weight desc, id asc), bound.
        seeds = sorted(direct_votes.items(), key=lambda kv: (-kv[1], kv[0]))[:_SEED_CAP]

        # 3. Vote tally seeded from the capped seeds' direct votes.
        scores: dict[str, int] = dict(seeds)
        dangling: set[str] = set()

        # 4. One-hop fan-out: propagate each seed's weight to its edge neighbours.
        #    A field-short/absent seed (husk) does not fan out; a field-short/absent
        #    neighbour is surfaced dangling, never propagated to.
        if fan_out:
            for nid, weight in seeds:
                seed_node = self._resolve_node(index, nid)
                if seed_node is None:
                    continue
                for neighbour in seed_node.get(index.edge_field, []):
                    if self._resolve_node(index, neighbour) is None:
                        dangling.add(neighbour)   # typed dangling, surfaced loud
                        continue
                    scores[neighbour] = scores.get(neighbour, 0) + weight

        # 5. Top-k via heap-top-k over a TWO-TIER composite key. Pre-order
        #    candidates by id asc so nlargest's stable decoration breaks full ties
        #    by node id ascending — the tertiary key. The key is (direct-vote tier,
        #    then the pre-fan-out direct-vote COUNT within the seed tier, else the
        #    accumulated vote score): a directly-matched seed (tier True) outranks
        #    every propagated-only neighbour (tier False) regardless of score, so no
        #    zero-direct-vote hub can evict a gold seed under the k cap; and seeds
        #    rank by direct-vote count, not accumulated score, so fan-out cannot
        #    re-order the seed tier.
        ordered = sorted(scores.items())
        top = heapq.nlargest(
            k,
            ordered,
            key=lambda kv: (
                kv[0] in direct_votes,
                direct_votes[kv[0]] if kv[0] in direct_votes else kv[1],
            ),
        )

        # 6. Hydrate the winners into the envelope; never emit a husk. Each node is
        #    resolved through the husk guard and deep-frozen at this boundary: a
        #    shallow ``{**node}`` would alias the singleton corpus's nested lists, so
        #    a caller mutating a returned node would corrupt the shared corpus.
        #    deep_freeze severs every reference and seals the copy.
        patterns: list[dict] = []
        votes: dict[str, int] = {}
        for nid, score in top:
            node = self._resolve_node(index, nid)
            if node is None:
                dangling.add(nid)
                continue
            direct = direct_votes.get(nid, 0)
            patterns.append(deep_freeze({
                **node,
                "retrieval": {
                    "score": score,
                    "direct_votes": direct,
                    "propagated_votes": score - direct,
                    "seed": nid in direct_votes,
                },
            }))
            votes[nid] = score

        # 7. Resolve the envelope state (fail closed).
        if not patterns:
            return RetrievalResult(
                state=DANGLING,
                dangling=sorted(dangling),
                unmatched_signals=sorted(set(unmatched)),
                reason="hydrated ids did not resolve to genuine corpus strategies",
            )
        top_score = patterns[0]["retrieval"]["score"]
        if top_score >= _CONFIDENCE_FLOOR:
            state, reason = HIT, ""
        else:
            state = LOW_CONFIDENCE
            reason = f"best score {top_score} below confidence floor {_CONFIDENCE_FLOOR}"
        return RetrievalResult(
            state=state,
            patterns=patterns,
            votes=votes,
            dangling=sorted(dangling),
            unmatched_signals=sorted(set(unmatched)),
            reason=reason,
        )


# The two named indices the engine serves. The strategy index (S1) fans out over the
# corpus's own ``alternatives`` edge; the agent-pattern index (S2) is edgeless —
# direct-vote-only detection with NO fabricated neighbours (fail closed). Both reuse
# every primitive above; the second index adds ZERO engine code.
_STRATEGY_INDEX_NAME = "strategies"
_AGENT_PATTERN_INDEX_NAME = "agent_patterns"


class KnowledgeLoader(_SignalEngine):
    """Loads and queries the Themis knowledge base (test strategies,
    agent patterns, frameworks).

    All matching is structural / exact / data-driven.  No fuzzy keyword overlap.
    Inherits the Shape-C signal-index retrieval engine (:class:`_SignalEngine`).
    """

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def __init__(self, knowledge_dir: Path | None = None) -> None:
        self._dir = knowledge_dir or _KNOWLEDGE_DIR

        with open(self._dir / "test_strategies.json", encoding="utf-8") as f:
            self._strategies_data = json.load(f)

        with open(self._dir / "agent_patterns.json", encoding="utf-8") as f:
            self._agent_patterns_data = json.load(f)

        with open(self._dir / "frameworks.json", encoding="utf-8") as f:
            self._frameworks_data = json.load(f)

        # Build convenience indices.
        self._strategies: list[dict] = self._strategies_data["strategies"]
        self._agent_patterns: list[dict] = self._agent_patterns_data["patterns"]
        self._frameworks: list[dict] = self._frameworks_data["frameworks"]

        # Index: strategy_id -> strategy_dict
        self._strategy_index: dict[str, dict] = {
            s["id"]: s for s in self._strategies
        }

        # Index: pattern_id -> pattern_dict
        self._pattern_index: dict[str, dict] = {
            p["id"]: p for p in self._agent_patterns
        }

        # Index: framework_id -> framework_dict
        self._framework_index: dict[str, dict] = {
            f["id"]: f for f in self._frameworks
        }

        # Shape-C strategy signal index (from each strategy's plural
        # ``structural_signals`` field, fan-out edge ``alternatives``). Built at
        # load so a hash collision fails CLOSED here, not at first query. This is the
        # ONLY strategy retrieval path: the corpus's own signals are the single source
        # of truth (the legacy substring matcher over the decision-rules table was
        # deleted at S5 once S3/S4 left it at zero callers). The engine is parameterized over this
        # ``_NamedIndex`` seam so the agent_patterns index reuses every primitive
        # (one engine, both corpora).
        self._strategy_signal_index = _NamedIndex(
            name=_STRATEGY_INDEX_NAME,
            node_index=self._strategy_index,
            signal_field="structural_signals",
            edge_field="alternatives",
            id_field="strategy_ids",
            required_fields=("structural_signals", "category"),
        )
        self._build_signal_index(self._strategy_signal_index)

        # Shape-C agent-pattern signal index (S2) — the SECOND named index, over each
        # agent_pattern's own ``signals`` field. agent_patterns.json carries NO edge, so
        # this view is DIRECT-VOTE-ONLY: hydrate never fans out (``edge_field=""`` is a
        # field no node has, and :meth:`hydrate_patterns` passes ``fan_out=False``), so a
        # matched pattern signal resolves to its OWN pattern node with no fabricated
        # neighbour — fail closed. Reuses every _SignalEngine primitive; zero duplicated
        # engine code. Disjoint id-map from the strategy index (the nested two-view is
        # collision-safe by construction even for the 4 texts shared across the corpora,
        # m-5a5837da). The agent-strategy <-> agent-pattern twin is a CROSS-LINK reference
        # (each agent strategy's ``agent_pattern`` id), never a copy across the views.
        self._pattern_signal_index = _NamedIndex(
            name=_AGENT_PATTERN_INDEX_NAME,
            node_index=self._pattern_index,
            signal_field="signals",
            edge_field="",
            id_field="pattern_ids",
            required_fields=("signals", "test_approach"),
        )
        self._build_signal_index(self._pattern_signal_index)

    # ------------------------------------------------------------------
    # Signal-index retrieval engine — S1-wired public API (strategy index)
    # ------------------------------------------------------------------
    # Thin bindings of the parameterized :class:`_SignalEngine` primitives to the
    # strategy index. These are the ONLY index wired at S1; S2 adds the nested
    # two-view over the agent_patterns index. The binding is the parameterization
    # seam, not a duplicate source of truth — the engine logic lives once above.
    # Engine-only at S1: no tools/*.py accessor and no server.py @mcp.tool wrapper
    # yet (those are S2's get_signal_index; S3/S4's plan_test_strategy /
    # evaluate_coverage retrofits).

    def get_signal_index(self) -> list[dict]:
        """Return the deterministic strategy signal-index view.

        Each entry is ``{signal_id, signal_text, strategy_ids}``, sorted by
        ``signal_id`` with sorted ``strategy_ids`` so it serialises identically on
        every call. The LLM recognises a problem's signals against this view and
        passes the matched ids to :meth:`hydrate`.
        """
        return self._signal_index_view(self._strategy_signal_index)

    def signal_ids_for(self, strategy_id: str) -> list[str]:
        """Return the signal ids of *strategy_id*'s own signals (seed-from-node)."""
        return self._signal_ids_for(self._strategy_signal_index, strategy_id)

    def hydrate(
        self,
        matched_signal_ids: list[str],
        k: int = 10,
        fan_out: bool = True,
    ) -> RetrievalResult:
        """Hydrate matched signal ids into ranked strategies (four-state envelope)."""
        return self._hydrate(self._strategy_signal_index, matched_signal_ids, k, fan_out)

    # ------------------------------------------------------------------
    # Signal-index retrieval engine — S2-wired public API (agent-pattern index)
    # ------------------------------------------------------------------
    # The SECOND view, over the agent_patterns corpus. Same parameterized engine, one
    # extra _NamedIndex; ``get_signal_index`` (tools/get_signal_index.py) composes this
    # with the strategy view into the nested two-view {strategy_signals, pattern_signals}.

    def get_pattern_signal_index(self) -> list[dict]:
        """Return the deterministic agent-pattern signal-index view.

        Each entry is ``{signal_id, signal_text, pattern_ids}``, sorted by ``signal_id``
        with sorted ``pattern_ids`` so it serialises identically on every call.
        """
        return self._signal_index_view(self._pattern_signal_index)

    def hydrate_patterns(
        self,
        matched_signal_ids: list[str],
        k: int = 10,
    ) -> RetrievalResult:
        """Hydrate matched signal ids into ranked agent patterns (four-state envelope).

        Direct-vote-only: agent_patterns carry no edge, so there is NO fan-out and no
        fabricated neighbour — a matched signal resolves to its own pattern node or the
        result abstains (NO_MATCH/DANGLING), never a husk.
        """
        return self._hydrate(self._pattern_signal_index, matched_signal_ids, k, fan_out=False)

    # ------------------------------------------------------------------
    # Pure retrieval — strategies
    # ------------------------------------------------------------------

    def get_strategy(self, strategy_id: str) -> dict | None:
        """Get a test strategy by ID."""
        return self._strategy_index.get(strategy_id)

    def get_strategies_by_ids(self, ids: list[str]) -> list[dict]:
        """Batch retrieval of strategies by ID."""
        results: list[dict] = []
        for sid in ids:
            s = self._strategy_index.get(sid)
            if s is not None:
                results.append(s)
        return results

    def get_all_strategies(self) -> list[dict]:
        """Get all test strategies."""
        return list(self._strategies)

    def get_strategies_by_category(self, category: str) -> list[dict]:
        """Get all strategies in a given category."""
        return [s for s in self._strategies if s.get("category") == category]

    # ------------------------------------------------------------------
    # Pure retrieval — agent patterns
    # ------------------------------------------------------------------

    def get_pattern(self, pattern_id: str) -> dict | None:
        """Get an agent testing pattern by ID."""
        return self._pattern_index.get(pattern_id)

    def get_all_agent_patterns(self) -> list[dict]:
        """Get all agent-specific testing patterns."""
        return list(self._agent_patterns)

    def get_agent_patterns_by_severity(self, severity: str) -> list[dict]:
        """Get agent patterns filtered by severity (critical/high/medium/low)."""
        return [p for p in self._agent_patterns if p.get("severity") == severity]

    def get_agent_patterns_by_adapter(self, adapter: str) -> list[dict]:
        """Get agent patterns that support a given adapter (websocket, http,
        stdio, stream)."""
        return [
            p for p in self._agent_patterns
            if adapter in p.get("adapters", [])
        ]

    # ------------------------------------------------------------------
    # Pure retrieval — frameworks
    # ------------------------------------------------------------------

    def get_framework(self, framework_id: str) -> dict | None:
        """Get a framework by ID."""
        return self._framework_index.get(framework_id)

    def get_all_frameworks(self) -> list[dict]:
        """Get all frameworks."""
        return list(self._frameworks)

    def get_frameworks_by_language(self, language: str) -> list[dict]:
        """Get frameworks that support a given language."""
        return [
            f for f in self._frameworks
            if f.get("language") == language or f.get("language") == "multi"
        ]

    def get_frameworks_by_category(self, category: str) -> list[dict]:
        """Get frameworks that support a given testing category."""
        return [
            f for f in self._frameworks
            if category in f.get("categories", [])
        ]

    def get_frameworks_with_agent_support(self) -> list[dict]:
        """Get frameworks with native or plugin agent testing support."""
        return [
            f for f in self._frameworks
            if f.get("agent_testing_support") in ("native", "plugin")
        ]

    # ------------------------------------------------------------------
    # Alternatives
    # ------------------------------------------------------------------

    def get_alternatives(self, strategy_id: str) -> list[dict]:
        """Find alternative strategies for *strategy_id*.

        Returns a list of strategy dicts for each alternative.
        """
        strategy = self._strategy_index.get(strategy_id)
        if strategy is None:
            return []

        alt_ids: list[str] = strategy.get("alternatives", [])
        results: list[dict] = []

        for alt_id in alt_ids:
            alt = self._strategy_index.get(alt_id)
            if alt is not None:
                results.append(alt)
            else:
                results.append({"id": alt_id, "name": alt_id})

        return results

    # ------------------------------------------------------------------
    # Compatible frameworks for a strategy
    # ------------------------------------------------------------------

    def get_compatible_frameworks(self, strategy_id: str) -> list[dict]:
        """Get full framework details for all compatible frameworks of a
        strategy."""
        strategy = self._strategy_index.get(strategy_id)
        if strategy is None:
            return []

        framework_ids: list[str] = strategy.get("compatible_frameworks", [])
        results: list[dict] = []

        for fid in framework_ids:
            fw = self._framework_index.get(fid)
            if fw is not None:
                results.append(fw)

        return results

    # ------------------------------------------------------------------
    # Compact index
    # ------------------------------------------------------------------

    def get_compact_index(self) -> list[dict]:
        """Return id + name + category + structural_signals only, for each
        strategy.

        Useful for the agent to scan available strategies without pulling
        full details.
        """
        results: list[dict] = []
        for s in self._strategies:
            results.append({
                "id": s["id"],
                "name": s.get("name", s["id"]),
                "category": s.get("category", ""),
                "structural_signals": s.get("structural_signals", []),
            })
        return results

    # ------------------------------------------------------------------
    # Constraint filtering — data-driven from strategy complexity
    # ------------------------------------------------------------------

    def filter_by_constraints(
        self,
        strategies: list[dict],
        constraints: dict,
    ) -> tuple[list[dict], list[dict]]:
        """Filter strategies by constraints.

        Args:
            strategies: List of strategy dicts (each must have ``complexity``
                with ``setup``, ``maintenance``, ``execution`` keys).
            constraints: Dict with optional keys:
                - ``language`` (str): target language
                - ``category`` (str): target category
                - ``max_setup`` (str): max setup complexity ("low"/"medium"/"high")
                - ``max_maintenance`` (str): max maintenance complexity
                - ``max_execution`` (str): max execution speed ("fast"/"medium"/"slow")
                - ``agent_testing_support`` (str): "native"/"plugin"/"none"

        Returns:
            (surviving, filtered_out) where each filtered_out entry has
            a ``filter_reason`` key explaining why it was removed.
        """
        language = constraints.get("language")
        category = constraints.get("category")
        max_setup = constraints.get("max_setup")
        max_maintenance = constraints.get("max_maintenance")
        max_execution = constraints.get("max_execution")
        agent_support = constraints.get("agent_testing_support")

        surviving: list[dict] = []
        filtered_out: list[dict] = []

        for strat in strategies:
            complexity = strat.get("complexity", {})
            reason = None

            # --- category filter ---
            if category and strat.get("category") != category:
                reason = f"category '{strat.get('category')}' != '{category}'"

            # --- setup complexity filter ---
            if reason is None and max_setup:
                setup = complexity.get("setup", "low")
                if _SETUP_RANK.get(setup, 0) > _SETUP_RANK.get(max_setup, 2):
                    reason = f"setup '{setup}' exceeds max '{max_setup}'"

            # --- maintenance complexity filter ---
            if reason is None and max_maintenance:
                maint = complexity.get("maintenance", "low")
                if _MAINTENANCE_RANK.get(maint, 0) > _MAINTENANCE_RANK.get(max_maintenance, 2):
                    reason = f"maintenance '{maint}' exceeds max '{max_maintenance}'"

            # --- execution speed filter ---
            if reason is None and max_execution:
                exec_speed = complexity.get("execution", "fast")
                if _EXECUTION_RANK.get(exec_speed, 0) > _EXECUTION_RANK.get(max_execution, 2):
                    reason = f"execution '{exec_speed}' exceeds max '{max_execution}'"

            # --- language filter (check compatible frameworks) ---
            if reason is None and language:
                fw_ids = strat.get("compatible_frameworks", [])
                has_lang = False
                for fid in fw_ids:
                    fw = self._framework_index.get(fid)
                    if fw and (fw.get("language") == language or fw.get("language") == "multi"):
                        has_lang = True
                        break
                if not has_lang:
                    reason = f"no compatible framework for language '{language}'"

            # --- agent testing support filter ---
            if reason is None and agent_support:
                fw_ids = strat.get("compatible_frameworks", [])
                has_support = False
                for fid in fw_ids:
                    fw = self._framework_index.get(fid)
                    if fw and fw.get("agent_testing_support") == agent_support:
                        has_support = True
                        break
                if not has_support:
                    reason = f"no framework with agent_testing_support='{agent_support}'"

            if reason:
                entry = dict(strat)
                entry["filter_reason"] = reason
                filtered_out.append(entry)
            else:
                surviving.append(strat)

        return surviving, filtered_out
