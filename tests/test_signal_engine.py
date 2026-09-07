# Copyright (c) 2026 Reza Malik. Licensed under the Apache License, Version 2.0.
"""Shape-C signal-index engine — unit proof (Themis S1, story-cefd1e71).

Locks the ported engine (a JUSTIFIED MIRROR of the shipped mnemos/coeus/theia
``_SignalEngine``; council 25d9a8ea / m-6ce2dcc3, standard m-55f6d4da):

* get_signal_index is deterministic + byte-reproducible (repeat calls, a fresh
  loader, and a PYTHONHASHSEED flip) and fails CLOSED on a hash collision at load;
* hydrate returns the four-state fail-closed envelope over the ``alternatives``
  edge, deep-frozen, no husk; NO_MATCH on empty/unrecognised ids; the DANGLING
  state and the field-short husk guard are exercised by CONSTRUCTED fixtures
  (Directive 8 — on the real corpus every seed resolves and every ``alternatives``
  edge points inside the strategy id-space, so neither is naturally reachable);
* the engine lives ONCE as ``_SignalEngine`` + module free-fns, inherited by BOTH
  loaders (the graph loader delegates its read path to the JSON parent).

All ids that drive a positive case are obtained from the accessor's OWN output
(``get_signal_index`` / ``signal_ids_for``), never hand-built (Directive 8).
Proven at the loader/testbed level only — no live othrys.db, no re-seed.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

import themis.knowledge.loader as L
from themis.knowledge.loader import (
    DANGLING,
    HIT,
    LOW_CONFIDENCE,
    NO_MATCH,
    _CONFIDENCE_FLOOR,
    _FrozenDict,
    _NamedIndex,
    _SEED_CAP,
    _SignalEngine,
    _TOPK_CAP,
    _signal_id,
    KnowledgeLoader,
    deep_freeze,
)

_SRC = Path(L.__file__).resolve().parents[2]  # .../src


@pytest.fixture(scope="module")
def kb() -> KnowledgeLoader:
    return KnowledgeLoader()


@pytest.fixture(scope="module")
def multi_signal_strategy(kb: KnowledgeLoader) -> str:
    """A strategy id that owns >= 2 structural signals (drives a multi-vote HIT).

    Chosen from the accessor's own view, deterministically (id asc)."""
    idx = kb.get_signal_index()
    counts: dict[str, int] = {}
    for e in idx:
        for sid in e["strategy_ids"]:
            counts[sid] = counts.get(sid, 0) + 1
    winners = sorted(s for s, c in counts.items() if c >= 2)
    assert winners, "expected at least one strategy with >= 2 own signals"
    return winners[0]


@pytest.fixture(scope="module")
def single_owner_signal(kb: KnowledgeLoader) -> str:
    """A signal id owned by exactly ONE strategy (drives a single-vote low_confidence)."""
    idx = kb.get_signal_index()
    singles = sorted(e["signal_id"] for e in idx if len(e["strategy_ids"]) == 1)
    assert singles, "expected at least one signal owned by exactly one strategy"
    return singles[0]


# ==========================================================================
# get_signal_index — determinism, byte-reproducibility, fail-closed collision
# ==========================================================================

class TestSignalIndex:
    def test_index_covers_all_distinct_signals(self, kb: KnowledgeLoader) -> None:
        idx = kb.get_signal_index()
        distinct = {
            s.strip()
            for st in kb.get_all_strategies()
            for s in st.get("structural_signals", [])
            if s.strip()
        }
        assert len(idx) == len(distinct)                 # every distinct strategy signal (226 post-S2-fold)
        assert all(e["signal_id"] == _signal_id(e["signal_text"]) for e in idx)
        assert all("strategy_ids" in e for e in idx)     # the strategy corpus id-field

    def test_deterministic_and_sorted(self, kb: KnowledgeLoader) -> None:
        a = kb.get_signal_index()
        b = kb.get_signal_index()
        assert a == b
        assert [e["signal_id"] for e in a] == sorted(e["signal_id"] for e in a)
        assert all(e["strategy_ids"] == sorted(e["strategy_ids"]) for e in a)

    def test_byte_reproducible_fresh_loader(self) -> None:
        dumps = [
            json.dumps(KnowledgeLoader().get_signal_index(), sort_keys=True)
            for _ in range(3)
        ]
        assert len(set(dumps)) == 1

    def test_byte_reproducible_across_pythonhashseed(self) -> None:
        """A PYTHONHASHSEED flip must not move the serialised index (real proof, not
        just the by-construction argument)."""
        snippet = (
            "import json,hashlib;"
            "from themis.knowledge.loader import KnowledgeLoader as K;"
            "print(hashlib.sha256(json.dumps(K().get_signal_index(),"
            "sort_keys=True).encode()).hexdigest())"
        )
        import os
        env_base = {**os.environ, "PYTHONPATH": str(_SRC)}
        outs = []
        for seed in ("0", "1", "12345"):
            r = subprocess.run(
                [sys.executable, "-c", snippet],
                capture_output=True, text=True,
                env={**env_base, "PYTHONHASHSEED": seed},
            )
            assert r.returncode == 0, r.stderr
            outs.append(r.stdout.strip())
        assert len(set(outs)) == 1, f"index sha256 moved across PYTHONHASHSEED: {outs}"

    def test_no_collision_on_real_corpus(self, kb: KnowledgeLoader) -> None:
        KnowledgeLoader()  # would raise in __init__ if the frozen corpus collided
        # 184 strategy-own signals + 42 decision_rules signals folded on at S2 = 226,
        # all distinct (0 hash collisions on the real corpus).
        assert len(kb.get_signal_index()) == 226

    def test_fail_closed_on_hash_collision(self, monkeypatch) -> None:
        """Two distinct signal texts colliding on one sid must raise at load, never
        silently merge into a corrupted index."""
        monkeypatch.setattr(L, "_signal_id", lambda _t: "sig-collide00000")
        eng = _SignalEngine()
        index = _NamedIndex(
            name="t", node_index={
                "a": {"id": "a", "structural_signals": ["foo shape"], "category": "c"},
                "b": {"id": "b", "structural_signals": ["bar shape"], "category": "c"},
            },
            signal_field="structural_signals", edge_field="alternatives",
            id_field="strategy_ids", required_fields=("structural_signals", "category"),
        )
        with pytest.raises(ValueError, match="collision"):
            eng._build_signal_index(index)


# ==========================================================================
# signal_ids_for — the seed-from-node accessor
# ==========================================================================

class TestSignalIdsFor:
    def test_returns_the_nodes_own_signal_ids(self, kb: KnowledgeLoader, multi_signal_strategy: str) -> None:
        sid = multi_signal_strategy
        strat = kb.get_strategy(sid)
        expected = sorted({_signal_id(s.strip()) for s in strat["structural_signals"] if s.strip()})
        assert kb.signal_ids_for(sid) == expected
        idx = {e["signal_id"]: e for e in kb.get_signal_index()}
        assert all(sid in idx[s]["strategy_ids"] for s in kb.signal_ids_for(sid))

    def test_unknown_or_none_seed_is_empty(self, kb: KnowledgeLoader) -> None:
        assert kb.signal_ids_for("no-such-strategy") == []
        assert kb.signal_ids_for("") == []

    def test_seed_hydrates_the_node_and_fans_out_over_alternatives(
        self, kb: KnowledgeLoader, multi_signal_strategy: str
    ) -> None:
        """Seeding hydrate with a node's own signal ids self-votes it (HIT) and fans
        out over its ``alternatives`` edge — the seed-from-node retrieval."""
        sid = multi_signal_strategy
        res = kb.hydrate(kb.signal_ids_for(sid), k=_TOPK_CAP)
        assert res.state == HIT
        ids = {p["id"] for p in res.patterns}
        assert sid in ids
        resolvable_alts = {a for a in kb.get_strategy(sid)["alternatives"] if kb.get_strategy(a)}
        assert resolvable_alts <= ids

    def test_deterministic_and_sorted(self, kb: KnowledgeLoader, multi_signal_strategy: str) -> None:
        a = kb.signal_ids_for(multi_signal_strategy)
        assert a == kb.signal_ids_for(multi_signal_strategy) == sorted(a)


# ==========================================================================
# hydrate — four-state fail-closed envelope over the ``alternatives`` edge
# ==========================================================================

class TestHydrateStates:
    def test_hit_multi_vote(self, kb: KnowledgeLoader, multi_signal_strategy: str) -> None:
        res = kb.hydrate(kb.signal_ids_for(multi_signal_strategy), k=10)
        assert res.state == HIT
        assert res.patterns[0]["retrieval"]["score"] >= _CONFIDENCE_FLOOR

    def test_low_confidence_single_vote(self, kb: KnowledgeLoader, single_owner_signal: str) -> None:
        res = kb.hydrate([single_owner_signal], k=10, fan_out=False)
        assert res.state == LOW_CONFIDENCE
        assert res.patterns                                # never an empty list narrated as an answer
        assert res.patterns[0]["retrieval"]["score"] < _CONFIDENCE_FLOOR

    def test_no_match_unrecognised_signal(self, kb: KnowledgeLoader) -> None:
        res = kb.hydrate(["sig-does-not-exist"], k=10)
        assert res.state == NO_MATCH
        assert res.patterns == []                          # fail closed, no husk
        assert res.votes == {}
        assert res.unmatched_signals == ["sig-does-not-exist"]

    def test_empty_input_is_no_match(self, kb: KnowledgeLoader) -> None:
        r = kb.hydrate([], k=10)
        assert r.state == NO_MATCH
        assert r.patterns == [] and r.unmatched_signals == []

    def test_dangling_state_constructed_fixture(self) -> None:
        """DANGLING state: EVERY hydrated id fails to resolve. Unreachable on the
        real corpus (seeds always resolve; every ``alternatives`` edge stays inside
        the strategy id-space), so it is built directly (Directive 8) — an index
        entry pointing only at an absent id."""
        loader = KnowledgeLoader()
        ghost = "sig-ghost0000000"
        loader._strategy_signal_index.signal_index[ghost] = {
            "signal_id": ghost, "signal_text": "ghost", "strategy_ids": ["__absent_strategy__"],
        }
        res = loader.hydrate([ghost], k=10)
        assert res.state == DANGLING
        assert res.patterns == []                          # no husk on DANGLING
        assert res.votes == {}
        assert "__absent_strategy__" in res.dangling

    def test_fanout_is_over_alternatives(self, kb: KnowledgeLoader, multi_signal_strategy: str) -> None:
        """A propagated (zero-direct-vote) neighbour must be a seed's ``alternatives``
        entry — proving fan-out walks the Themis edge. With fan-out off, only the
        direct seed survives."""
        sid = multi_signal_strategy
        resolvable_alts = {a for a in kb.get_strategy(sid)["alternatives"] if kb.get_strategy(a)}
        res = kb.hydrate(kb.signal_ids_for(sid), k=_TOPK_CAP, fan_out=True)
        propagated = {p["id"] for p in res.patterns if not p["retrieval"]["seed"]}
        assert resolvable_alts & propagated
        res_off = kb.hydrate(kb.signal_ids_for(sid), k=_TOPK_CAP, fan_out=False)
        assert all(p["retrieval"]["seed"] for p in res_off.patterns)
        assert all(p["retrieval"]["propagated_votes"] == 0 for p in res_off.patterns)


# ==========================================================================
# Husk guard — a FIELD-SHORT node resolves to DANGLING, never a silent default
# (Hyperion fail-closed AC). Constructed fixtures (Directive 8).
# ==========================================================================

class TestHuskGuard:
    def test_field_short_seed_is_not_hydrated_as_a_husk(self) -> None:
        """A node present in the index but missing a required field (the ``{id, name}``
        husk shape) resolves to DANGLING, not a silently-defaulted node."""
        loader = KnowledgeLoader()
        husk_id = "__husk_strategy__"
        loader._strategy_index[husk_id] = {"id": husk_id, "name": husk_id}  # no signals/category
        sid = "sig-husk00000000"
        loader._strategy_signal_index.signal_index[sid] = {
            "signal_id": sid, "signal_text": "husk", "strategy_ids": [husk_id],
        }
        res = loader.hydrate([sid], k=10)
        assert res.state == DANGLING
        assert res.patterns == []                          # never emitted as a husk
        assert husk_id in res.dangling

    def test_field_short_neighbour_is_surfaced_dangling_not_propagated(self, kb: KnowledgeLoader) -> None:
        """A field-short ``alternatives`` neighbour populates the dangling FIELD on an
        otherwise-HIT envelope — surfaced loud, never hydrated as a husk."""
        loader = KnowledgeLoader()
        # a genuine multi-signal seed, plus a husk wired into its alternatives edge
        idx = {e["signal_id"]: e for e in loader.get_signal_index()}
        counts: dict[str, int] = {}
        for e in idx.values():
            for s in e["strategy_ids"]:
                counts[s] = counts.get(s, 0) + 1
        seed_id = sorted(s for s, c in counts.items() if c >= 2)[0]
        husk_id = "__husk_alt__"
        loader._strategy_index[husk_id] = {"id": husk_id, "name": husk_id}
        real = loader._strategy_index[seed_id]
        loader._strategy_index[seed_id] = {**real, "alternatives": [*real.get("alternatives", []), husk_id]}
        res = loader.hydrate(loader.signal_ids_for(seed_id), k=_TOPK_CAP)
        assert res.state == HIT                            # the genuine seed still hits
        assert husk_id in res.dangling                     # the husk neighbour surfaced
        assert husk_id not in {p["id"] for p in res.patterns}   # never hydrated

    def test_genuine_node_passes_the_guard(self, kb: KnowledgeLoader) -> None:
        """The guard does not fire on the real corpus: every strategy carries the
        required fields, so a real signal hydrates to a real node."""
        idx = kb.get_signal_index()
        res = kb.hydrate([idx[0]["signal_id"]], k=10)
        assert res.state in (HIT, LOW_CONFIDENCE)
        assert res.patterns and res.dangling == []


class TestHydrateInvariants:
    def test_deep_frozen_patterns_are_read_only(self, kb: KnowledgeLoader, multi_signal_strategy: str) -> None:
        res = kb.hydrate(kb.signal_ids_for(multi_signal_strategy), k=5)
        p = res.patterns[0]
        assert isinstance(p, _FrozenDict)
        with pytest.raises(TypeError):
            p["id"] = "tampered"
        assert isinstance(p["structural_signals"], tuple)
        with pytest.raises(AttributeError):
            p["structural_signals"].append("x")

    def test_hydrate_does_not_corrupt_corpus(self, kb: KnowledgeLoader, multi_signal_strategy: str) -> None:
        sid = multi_signal_strategy
        before = list(kb.get_strategy(sid)["alternatives"])
        kb.hydrate(kb.signal_ids_for(sid), k=_TOPK_CAP)
        assert kb.get_strategy(sid)["alternatives"] == before

    def test_ranking_deterministic(self, kb: KnowledgeLoader, multi_signal_strategy: str) -> None:
        sigs = kb.signal_ids_for(multi_signal_strategy)
        runs = [[p["id"] for p in kb.hydrate(sigs, k=10).patterns] for _ in range(5)]
        assert all(r == runs[0] for r in runs)
        fresh = [p["id"] for p in KnowledgeLoader().hydrate(sigs, k=10).patterns]
        assert fresh == runs[0]

    def test_k_bound_is_a_prefix(self, kb: KnowledgeLoader, multi_signal_strategy: str) -> None:
        sigs = kb.signal_ids_for(multi_signal_strategy)
        full = [p["id"] for p in kb.hydrate(sigs, k=_TOPK_CAP).patterns]
        k2 = [p["id"] for p in kb.hydrate(sigs, k=2).patterns]
        assert k2 == full[:2]

    def test_two_tier_seed_outranks_pure_hub(self, kb: KnowledgeLoader, multi_signal_strategy: str) -> None:
        """A directly-matched seed (tier True) is never displaced from the top by a
        zero-direct-vote fan-out neighbour."""
        res = kb.hydrate(kb.signal_ids_for(multi_signal_strategy), k=_TOPK_CAP)
        assert res.patterns[0]["retrieval"]["seed"] is True

    def test_ceilings_unchanged(self) -> None:
        assert (_SEED_CAP, _TOPK_CAP, _CONFIDENCE_FLOOR) == (64, 50, 2)


# ==========================================================================
# Free-function primitives (deep_freeze) + facet gate (ported, DORMANT)
# ==========================================================================

class TestPrimitives:
    def test_deep_freeze_severs_references(self) -> None:
        src = {"a": [1, 2, {"b": 3}]}
        frozen = deep_freeze(src)
        assert isinstance(frozen, _FrozenDict)
        assert isinstance(frozen["a"], tuple)
        assert isinstance(frozen["a"][2], _FrozenDict)
        src["a"].append(99)                 # mutating the source must not touch the copy
        assert 99 not in frozen["a"]

    def test_facet_gate_dormant_on_strategy_corpus(self, kb: KnowledgeLoader) -> None:
        """The ported facet gate is DORMANT: no Themis strategy carries an avoid_when
        facet dict, so is_gated is always False (the LIVE gate is filter_by_constraints)."""
        for strat in kb.get_all_strategies():
            assert L.is_gated(strat, {"team_size": "1", "scale": "startup"}) is False

    def test_split_conditions_partitions_by_type(self) -> None:
        texts, facets = L.split_conditions(["free text", {"team_size": "1-5"}, "more text"])
        assert texts == ["free text", "more text"]
        assert facets == [{"team_size": "1-5"}]

    def test_parse_team_range(self) -> None:
        assert L._parse_team_range("1-5") == (1, 5)
        assert L._parse_team_range("3") == (3, 3)
        assert L._parse_team_range("50+")[0] == 50
        assert L._parse_team_range("garbage") is None


# ==========================================================================
# Agent-pattern signal index (S2) — the SECOND view, direct-vote-only, no edge
# ==========================================================================

def _pattern_sig_ids(kb: KnowledgeLoader) -> dict[str, list[str]]:
    """pattern_id -> its own signal ids, from the accessor's own view (Directive 8)."""
    out: dict[str, list[str]] = {}
    for e in kb.get_pattern_signal_index():
        for pid in e["pattern_ids"]:
            out.setdefault(pid, []).append(e["signal_id"])
    return out


class TestPatternSignalIndex:
    def test_index_shape_count_and_sorted(self, kb: KnowledgeLoader) -> None:
        idx = kb.get_pattern_signal_index()
        assert len(idx) == 60                              # 60 distinct agent-pattern signals
        assert all(e["signal_id"] == _signal_id(e["signal_text"]) for e in idx)
        assert all("pattern_ids" in e for e in idx)        # the pattern corpus id-field
        assert [e["signal_id"] for e in idx] == sorted(e["signal_id"] for e in idx)
        assert all(e["pattern_ids"] == sorted(e["pattern_ids"]) for e in idx)

    def test_deterministic_and_disjoint_map_from_strategy_view(self, kb: KnowledgeLoader) -> None:
        assert kb.get_pattern_signal_index() == kb.get_pattern_signal_index()
        # The two views are SEPARATE maps: the 4 texts shared across the corpora keep a
        # signal in each view's own map (nested two-view is collision-safe, m-5a5837da).
        strat_ids = {e["signal_id"] for e in kb.get_signal_index()}
        pat_ids = {e["signal_id"] for e in kb.get_pattern_signal_index()}
        shared = strat_ids & pat_ids
        assert shared, "expected the collision texts to share a loader id across the two view-maps"

    def test_hydrate_patterns_is_direct_vote_only_no_fabricated_neighbour(
        self, kb: KnowledgeLoader
    ) -> None:
        """A pattern seeded by >= 2 of its own signals HITs, and EVERY hydrated node is a
        direct-vote seed — agent_patterns carry no edge, so there is never a propagated
        neighbour (fail closed, no fabrication)."""
        by_pat = _pattern_sig_ids(kb)
        pid = next(p for p, sigs in sorted(by_pat.items()) if len(sigs) >= _CONFIDENCE_FLOOR)
        res = kb.hydrate_patterns(by_pat[pid], k=_TOPK_CAP)
        assert res.state == HIT
        assert pid in {p["id"] for p in res.patterns}
        assert all(p["retrieval"]["seed"] for p in res.patterns)
        assert all(p["retrieval"]["propagated_votes"] == 0 for p in res.patterns)

    def test_hydrate_patterns_fail_closed(self, kb: KnowledgeLoader) -> None:
        assert kb.hydrate_patterns([]).state == NO_MATCH
        assert kb.hydrate_patterns([]).patterns == []
        assert kb.hydrate_patterns(["sig-does-not-exist"]).state == NO_MATCH

    def test_pattern_signal_round_trips_to_its_node(self, kb: KnowledgeLoader) -> None:
        """A real signal_id from the live accessor hydrates back to its pattern node."""
        e = kb.get_pattern_signal_index()[0]
        res = kb.hydrate_patterns([e["signal_id"]], k=10)
        assert res.state in (HIT, LOW_CONFIDENCE)
        assert set(e["pattern_ids"]) <= {p["id"] for p in res.patterns}
        assert res.dangling == []


# ==========================================================================
# Dual-loader — ONE engine, both loaders inherit it (no live DB required:
# the graph loader delegates its read path to the JSON parent)
# ==========================================================================

class TestDualLoader:
    def test_both_loaders_inherit_one_engine(self) -> None:
        from themis.knowledge.graph_loader import GraphKnowledgeLoader
        assert issubclass(KnowledgeLoader, _SignalEngine)
        assert issubclass(GraphKnowledgeLoader, _SignalEngine)
        # the engine methods are the SAME objects on both (no duplicate engine code)
        assert KnowledgeLoader._hydrate is _SignalEngine._hydrate
        assert GraphKnowledgeLoader._hydrate is _SignalEngine._hydrate
        assert KnowledgeLoader._build_signal_index is _SignalEngine._build_signal_index
        # the public bindings (S1 strategy view + S2 agent-pattern view) are inherited
        # unchanged by the graph loader
        assert GraphKnowledgeLoader.get_signal_index is KnowledgeLoader.get_signal_index
        assert GraphKnowledgeLoader.hydrate is KnowledgeLoader.hydrate
        assert GraphKnowledgeLoader.get_pattern_signal_index is KnowledgeLoader.get_pattern_signal_index
        assert GraphKnowledgeLoader.hydrate_patterns is KnowledgeLoader.hydrate_patterns
