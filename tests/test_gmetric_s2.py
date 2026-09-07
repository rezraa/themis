# Copyright (c) 2026 Reza Malik. Licensed under the Apache License, Version 2.0.
"""themis-Gmetric S2 gate — the two-view Shape-C engine clears the S0-locked legs
(story-6c63a3bd; council 25d9a8ea / m-6ce2dcc3).

The RED gate S0 armed (locked_legs_v1.json) is cleared here, REPRODUCED not re-derived,
by feeding the SAME frozen problems/golds/strata through the ported production engine
(``loader.hydrate`` over the strategy view + ``loader.hydrate_patterns`` over the
agent-pattern view) and grading with ``grade.grade`` verbatim — over the v2 substrate
(the corpus after decision_rules is dissolved onto the strategy corpus at S2). Every
number is per-stratum, never pooled (m-e8ccb163).

  * LEG_1  no-regression on EVERY stratum vs the S0 baseline snapshot (one-sided gain).
  * LEG_2  S-PL recall@10(engine) - baseline >= 0.30 (the paraphrase register the
           substring matcher structurally cannot serve; the S2 fold lifts it).
  * LEG_3  pattern-target recall@10(engine) >= 0.40 (the agent_patterns corpus the
           matcher has no route to; the S2 pattern index lifts it).

Substrate is pinned two ways, both fail-closed: the v2 corpus/benchmark via the frozen
freeze_manifest_v2.json (grade._verify_substrate), and the engine recognizer via
themis_engine_matches_freeze_v2.json. Recognition is proven REPRODUCIBLE (live ==
frozen) and gold-blind (the engine bench never reads the answer key), so no hand-edit
can hide in the frozen file.

The live summon('themis','get_signal_index') proof is the USER's post-re-seed step; this
gate proves the AC at loader/accessor level. No live DB is opened.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GMETRIC = REPO / "tests" / "data" / "gmetric"
sys.path.insert(0, str(GMETRIC))

# S2 re-freeze: grade against the v2 generation (post decision_rules dissolution).
# Set BEFORE importing grade — grade resolves its frozen-artifact paths at import from
# THEMIS_GMETRIC_VERSION (default v1 preserves S0 provenance).
os.environ["THEMIS_GMETRIC_VERSION"] = "v2"

import grade  # noqa: E402  (path-injected frozen grader, v2-selected, reused verbatim)
import themis_engine_bench as eng  # noqa: E402  (two-view Shape-C harness)
from themis.knowledge.loader import KnowledgeLoader  # noqa: E402

PY = sys.executable
LEGS = json.loads((GMETRIC / "locked_legs_v1.json").read_text(encoding="utf-8"))
ENGINE_MATCHES = json.loads((GMETRIC / "themis_engine_matches_v2.json").read_text(encoding="utf-8"))
ENGINE_FREEZE = json.loads((GMETRIC / "themis_engine_matches_freeze_v2.json").read_text(encoding="utf-8"))


def _canon(obj) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def _by_stratum(core: dict) -> dict:
    return {s: v["10"]["recall"] for s, v in core["by_stratum"].items()}


def _by_target(core: dict) -> dict:
    return {s: v["10"]["recall"] for s, v in core["by_target"].items()}


@pytest.fixture(scope="module")
def engine_core() -> dict:
    """Grade the two-view Shape-C engine ONCE through the real grader + production hydrate."""
    return grade.grade(eng.rank_engine, "shape_c_two_view_engine")


# ==========================================================================
# Substrate — fail closed on any drift (v2 corpus + engine recognizer)
# ==========================================================================

class TestSubstrate:
    def test_v2_grade_generation_selected(self) -> None:
        assert grade._VER == "v2"
        assert grade.GMETRIC_IN.name == "gmetric_v2.json"

    def test_v2_corpus_substrate_matches_frozen_pins(self) -> None:
        """The v2 corpus/benchmark is unchanged (grade's own verifier, verbatim)."""
        checks = grade._verify_substrate()  # raises SystemExit on any drift
        assert all(c["match"] for c in checks.values())

    def test_answer_key_unchanged_from_v1(self) -> None:
        """Same problems/golds/strata: the v2 answer key is byte-identical to v1's."""
        v1 = json.loads((GMETRIC / "gmetric_v1.json").read_text(encoding="utf-8"))
        v2 = json.loads((GMETRIC / "gmetric_v2.json").read_text(encoding="utf-8"))
        assert v1["answer_key_sha256"] == v2["answer_key_sha256"]

    def test_engine_recognition_is_reproducible(self) -> None:
        """Live recognition == the frozen snapshot (no hidden hand-edit), and it is
        gold-blind (the bench never reads gmetric)."""
        live = eng.build_matches(KnowledgeLoader(knowledge_dir=grade.KDIR))
        assert live == ENGINE_MATCHES["matches"]
        assert hashlib.sha256(_canon(live).encode()).hexdigest() == \
            ENGINE_FREEZE["themis_engine_matches_sha256"]

    def test_all_matched_signals_resolve_in_their_view(self) -> None:
        kb = KnowledgeLoader(knowledge_dir=grade.KDIR)
        strat_ids = {e["signal_id"] for e in kb.get_signal_index()}
        pat_ids = {e["signal_id"] for e in kb.get_pattern_signal_index()}
        for pid, views in ENGINE_MATCHES["matches"].items():
            assert all(s in strat_ids for s in views["strategy"]), f"{pid} strategy id unresolved"
            assert all(s in pat_ids for s in views["pattern"]), f"{pid} pattern id unresolved"

    def test_engine_bench_never_reads_the_answer_key(self) -> None:
        """Static proof: the engine bench references no gmetric FILE PATH and imports no
        sibling (themis-only firewall)."""
        tree = ast.parse((GMETRIC / "themis_engine_bench.py").read_text(encoding="utf-8"))
        literals = [n.value for n in ast.walk(tree)
                    if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        assert not any(lit.strip().endswith(".json") for lit in literals)
        assert not any("gmetric" in lit for lit in literals if lit.strip().endswith(".json"))
        forbidden = ("othrys", "coeus", "mnemos", "theia", "hyperion", "phoebe")
        names: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names.append(node.module or "")
        assert not any(n.split(".")[0] in forbidden for n in names), names


# ==========================================================================
# The three S0-locked legs, reproduced through the two-view hydrate path
# ==========================================================================

class TestLegs:
    def test_denominator_is_the_frozen_36(self, engine_core: dict) -> None:
        assert engine_core["denominator_E_golds"] == 36

    def test_leg_1_no_regression_every_stratum(self, engine_core: dict) -> None:
        leg = LEGS["legs"]["LEG_1_no_regression"]
        base = leg["baseline_by_stratum"]
        eng_s = _by_stratum(engine_core)
        assert leg["one_sided_gain_inspection"] is True
        for stratum, floor in base.items():
            assert eng_s[stratum] >= floor, f"{stratum}: {eng_s[stratum]} < baseline {floor}"

    def test_leg_2_strategy_problem_language_lift(self, engine_core: dict) -> None:
        leg = LEGS["legs"]["LEG_2_strategy_problem_language_lift"]
        delta = round(_by_stratum(engine_core)["S-PL"] - leg["baseline"], 4)
        assert delta >= leg["min_delta"], f"S-PL lift {delta} < {leg['min_delta']}"

    def test_leg_3_agent_pattern_reach(self, engine_core: dict) -> None:
        leg = LEGS["legs"]["LEG_3_agent_pattern_reach"]
        reach = _by_target(engine_core)["pattern"]
        assert reach >= leg["floor"], f"pattern-target reach {reach} < {leg['floor']}"

    def test_both_strata_families_cleared(self, engine_core: dict) -> None:
        """The AC bar: re-frozen per-stratum recall@10 >= baseline on BOTH the strategy
        AND the pattern strata (never a pooled mean, m-e8ccb163)."""
        eng_s = _by_stratum(engine_core)
        # strategy strata well above baseline (S-V 0.6, S-PL 0.0)
        assert eng_s["S-V"] >= 0.6 and eng_s["S-PL"] >= 0.30
        # pattern strata off the floor the matcher could never leave (both baseline 0.0)
        assert eng_s["P-V"] > 0.0 and eng_s["P-PL"] > 0.0

    def test_verdict_all_three_legs(self, engine_core: dict) -> None:
        eng_s, eng_t = _by_stratum(engine_core), _by_target(engine_core)
        legs = LEGS["legs"]
        leg1 = all(eng_s[k] >= v for k, v in legs["LEG_1_no_regression"]["baseline_by_stratum"].items())
        leg2 = round(eng_s["S-PL"] - legs["LEG_2_strategy_problem_language_lift"]["baseline"], 4) \
            >= legs["LEG_2_strategy_problem_language_lift"]["min_delta"]
        leg3 = eng_t["pattern"] >= legs["LEG_3_agent_pattern_reach"]["floor"]
        assert leg1 and leg2 and leg3

    def test_no_pooled_mean(self, engine_core: dict) -> None:
        assert "by_stratum" in engine_core and "by_target" in engine_core
        assert "pooled_do_not_use" in engine_core
        assert "recall" not in engine_core  # no top-level pooled recall masquerading


# ==========================================================================
# Determinism + fail-closed control
# ==========================================================================

class TestDeterminismAndControl:
    def test_determinism_three_fresh_runs(self) -> None:
        shas = {hashlib.sha256(_canon(grade.grade(eng.rank_engine, "e")).encode()).hexdigest()
                for _ in range(3)}
        assert len(shas) == 1

    def test_determinism_across_pythonhashseed(self) -> None:
        shas = set()
        for seed in ("0", "1", "42"):
            out = subprocess.run(
                [PY, "-c",
                 "import grade,hashlib,json;import themis_engine_bench as e;"
                 "c=grade.grade(e.rank_engine,'e');"
                 "print(hashlib.sha256((json.dumps(c,indent=2,sort_keys=True,ensure_ascii=True)+chr(10)).encode()).hexdigest())"],
                cwd=str(GMETRIC),
                env={"PYTHONHASHSEED": seed, "PYTHONPATH": str(REPO / "src"),
                     "THEMIS_GMETRIC_VERSION": "v2",
                     "SYSTEMROOT": os.environ.get("SYSTEMROOT", "")},
                capture_output=True, text=True)
            assert out.returncode == 0, out.stderr
            shas.add(out.stdout.strip())
        assert len(shas) == 1

    def test_empty_recognition_is_no_match(self) -> None:
        kb = KnowledgeLoader(knowledge_dir=grade.KDIR)
        assert eng.rank_engine(kb, [""]) == []            # the P_EMPTY control
        assert kb.hydrate([]).state == "no_match"
        assert kb.hydrate_patterns([]).state == "no_match"


# ==========================================================================
# The filed nested two-view accessor (AC) + round-trip
# ==========================================================================

class TestAccessor:
    def test_get_signal_index_nested_two_view_shape(self) -> None:
        from themis.tools.get_signal_index import get_signal_index
        idx = get_signal_index()
        assert set(idx) == {"strategy_signals", "pattern_signals"}
        for e in idx["strategy_signals"]:
            assert set(e) == {"signal_id", "signal_text", "strategy_ids"}
        for e in idx["pattern_signals"]:
            assert set(e) == {"signal_id", "signal_text", "pattern_ids"}
        assert len(idx["strategy_signals"]) == 226 and len(idx["pattern_signals"]) == 60

    def test_one_public_function_in_the_tool_module(self) -> None:
        """AC: filename == function; exactly ONE public top-level function (the Othrys
        filename-keyed-seed reachability contract, m-5a5837da)."""
        import themis.tools.get_signal_index as mod
        publics = [n for n in vars(mod)
                   if not n.startswith("_") and callable(getattr(mod, n))
                   and getattr(getattr(mod, n), "__module__", None) == mod.__name__]
        assert publics == ["get_signal_index"]

    def test_real_signal_id_round_trips_through_hydrate(self) -> None:
        """AC proof: a real signal_id from the live accessor round-trips through hydrate
        to its node — on BOTH views."""
        from themis.tools.get_signal_index import get_signal_index
        kb = KnowledgeLoader(knowledge_dir=grade.KDIR)
        idx = get_signal_index()
        se = idx["strategy_signals"][0]
        sr = kb.hydrate([se["signal_id"]], k=10)
        assert set(se["strategy_ids"]) <= {p["id"] for p in sr.patterns}
        pe = idx["pattern_signals"][0]
        pr = kb.hydrate_patterns([pe["signal_id"]], k=10)
        assert set(pe["pattern_ids"]) <= {p["id"] for p in pr.patterns}

    def test_cross_link_references_existing_pattern_ids(self) -> None:
        """AC: agent-category strategies cross-link to their twin agent_patterns by
        EXISTING id (reference, not duplication)."""
        kb = KnowledgeLoader(knowledge_dir=grade.KDIR)
        pattern_ids = {p["id"] for p in kb.get_all_agent_patterns()}
        linked = [s for s in kb.get_all_strategies() if "agent_pattern" in s]
        assert len(linked) == 12
        for s in linked:
            assert s["category"] == "agent"
            assert s["agent_pattern"] in pattern_ids
