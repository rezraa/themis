# Copyright (c) 2026 Reza Malik. Licensed under the Apache License, Version 2.0.
"""themis-Gmetric-v1 S0 gate (story-350b3817).

The RED gate that blocked the S1+ retrofit until every stratum was measured. It asserts,
against the byte-frozen artifacts, every AC deliverable:

  * reachable denominator = 244 signals (184 strategy + 60 pattern), frameworks EXCLUDED;
  * matcher-reachable ceiling = 16/184 strategy + 2/60 pattern (the premise crux);
  * id-space collision enumeration = 4 texts, and the per-kind hash keeps them distinct
    while a flat text-only hash would merge them (the S2 nested-view rationale);
  * baseline recall@10 per stratum, NEVER pooled, reproducing the ceiling (S-V 0.60 proves
    non-strawman; S-PL / P-V / P-PL = 0.0);
  * blindness (SHAPE smuggles no gold; live recognizer == frozen snapshot);
  * the grader BITES a planted retrieval regression (built failing-first);
  * fail-closed substrate trust root (CWE-345);
  * import firewall (themis.* only).

S5 UPDATE (story-9e3ae299): the legacy substring matcher was deleted once S3/S4 left it
at zero callers. Its baseline result core is permanently frozen in
baseline_matcher_pinned_v2.json and read via grade.load_pinned_baseline() — never
recomputed, because no matcher remains to run. The baseline-recompute and matcher-runtime
legs were repointed to the pin or retired; the live-engine determinism, empty-recognition
control, and PYTHONHASHSEED legs live in test_gmetric_s2. The decision-rules table stays on
disk as sha-pinned substrate (still verified by _verify_substrate).
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
GMETRIC = REPO / "tests" / "data" / "gmetric"
KDIR = REPO / "src" / "themis" / "knowledge"
sys.path.insert(0, str(GMETRIC))

# S2 re-freeze: the S0 gate reconciled to the CURRENT (v2) substrate. The v1 FROZEN
# artifacts (gmetric_v1.json et al.) remain on disk and this file still asserts the S0
# RECORD against them (the pre-fold 244 denominator, 16/2 ceiling, 4 collisions, blind
# recognizer snapshot, answer-key hash). The grade-driven and live-corpus checks run
# against v2 — after decision_rules is dissolved onto the strategy corpus the v1 corpus
# pins legitimately drift (the tamper-evidence firing correctly), so grade verifies v2.
# Set BEFORE importing grade/build (both resolve their generation at import).
os.environ["THEMIS_GMETRIC_VERSION"] = "v2"

import build_gmetric_v1  # noqa: E402
import grade  # noqa: E402
import themis_engine_bench as eng  # noqa: E402
import themis_recognizer as tr  # noqa: E402
from themis.knowledge.loader import KnowledgeLoader  # noqa: E402


def _loader() -> KnowledgeLoader:
    return KnowledgeLoader(knowledge_dir=KDIR)


def _rules_on_disk() -> list[dict]:
    """The decision-rules table read straight from the frozen substrate FILE (the loader no
    longer loads it; the file is kept, sha-pinned, as benchmark substrate)."""
    return json.loads((KDIR / "decision_rules.json").read_text(encoding="utf-8"))["rules"]


def _gmetric() -> dict:
    return json.loads((GMETRIC / "gmetric_v1.json").read_text(encoding="utf-8"))


def _canon(obj) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


# --------------------------------------------------------------------------- #
# Corpus shape + reachable denominator
# --------------------------------------------------------------------------- #

def test_corpus_counts():
    ld = _loader()
    assert len(ld.get_all_strategies()) == 47
    assert len(ld.get_all_agent_patterns()) == 12
    assert len(_rules_on_disk()) == 45    # decision-rules table KEPT on disk as substrate
    vocab = tr.build_vocabulary(ld)
    # S2 fold: 184 strategy-own signals + 42 decision_rules signals dissolved on = 226.
    # The pre-fold 184 is preserved as the S0 record in gmetric_v1.json (below).
    assert len(vocab["strategy"]) == 226
    assert len(vocab["pattern"]) == 60
    assert _gmetric()["reachable_denominator"]["strategy_signals"] == 184  # frozen S0 record


def test_reachable_denominator_244_frameworks_excluded():
    g = _gmetric()["reachable_denominator"]
    assert g["strategy_signals"] == 184
    assert g["pattern_signals"] == 60
    assert g["total"] == 244
    assert "frameworks" in g["note"].lower() and "exclud" in g["note"].lower()


# --------------------------------------------------------------------------- #
# Matcher-reachable ceiling (the premise crux)
# --------------------------------------------------------------------------- #

def test_matcher_reachable_ceiling_16_and_2():
    c = _gmetric()["matcher_reachable_ceiling"]
    assert c["strategy_signals_reachable"] == 16
    assert c["strategy_signals_total"] == 184
    assert c["pattern_signals_reachable"] == 2
    assert c["pattern_signals_total"] == 60
    assert c["rule_signals_indexed"] == 45


def test_ceiling_recomputes_independently():
    """Re-derive the substring-reachable ceiling from the loader, trusting nothing in
    gmetric. Post-S2-fold the 42 dissolved rule signals now live on the strategy corpus
    and are reachable-by-construction, so the strategy ceiling lifts from the S0 16 to 58
    (that lift is exactly what S2 delivers); the pattern ceiling is untouched at 2. Both
    the frozen S0 record (16/2 in gmetric_v1.json) and the re-frozen v2 record (58/2)
    are cross-checked."""
    ld = _loader()
    vocab = tr.build_vocabulary(ld)
    rule_sigs = sorted({r["structural_signal"].strip().lower()
                        for r in _rules_on_disk() if r.get("structural_signal")})

    def reach(text):
        t = text.strip().lower()
        return any(t in r or r in t for r in rule_sigs)

    strat = sum(1 for r in vocab["strategy"] if reach(r["signal_text"]))
    pat = sum(1 for r in vocab["pattern"] if reach(r["signal_text"]))
    assert (strat, pat) == (58, 2)                        # post-fold live recompute
    # frozen records: S0 (pre-fold) and the v2 re-freeze.
    assert _gmetric()["matcher_reachable_ceiling"]["strategy_signals_reachable"] == 16
    v2 = json.loads((GMETRIC / "gmetric_v2.json").read_text(encoding="utf-8"))
    assert v2["matcher_reachable_ceiling"]["strategy_signals_reachable"] == 58
    assert v2["matcher_reachable_ceiling"]["pattern_signals_reachable"] == 2


# --------------------------------------------------------------------------- #
# Id-space collision enumeration (feeds the S2 nested-view decision)
# --------------------------------------------------------------------------- #

def test_collision_enumeration_is_four():
    col = _gmetric()["collisions"]
    assert col["collision_count"] == 4
    assert col["collision_texts"] == [
        "long conversation sessions",
        "production reliability requirement",
        "public-facing ai agent",
        "rag-based agent with source documents",
    ]


def test_flat_hash_collides_per_kind_hash_does_not():
    col = _gmetric()["collisions"]
    # A flat text-only hash would merge all four; the per-kind hash used here merges none.
    assert col["flat_text_hash_would_collide"] == 4
    assert col["per_kind_hash_collisions"] == 0
    for t in col["collision_texts"]:
        assert tr.sig_id("strategy", t) != tr.sig_id("pattern", t)


# --------------------------------------------------------------------------- #
# Baseline recall -- stratified, never pooled, reproduces the ceiling
# --------------------------------------------------------------------------- #

def test_baseline_recall_per_stratum_reproduces_ceiling():
    # The matcher was deleted at S5; its baseline is read from the pin, never recomputed.
    core = grade.load_pinned_baseline()
    r = {s: v["10"]["recall"] for s, v in core["by_stratum"].items()}
    assert r["S-V"] == 0.6      # non-strawman: matcher answered its own rule-idiom
    assert r["S-PL"] == 0.0     # paraphrase: substring matcher could not serve it
    assert r["P-V"] == 0.0      # matcher had no route to agent_patterns, even verbatim
    assert r["P-PL"] == 0.0
    # AGENT-PATTERN target near-zero (exactly 0) -- the ceiling this benchmark exposed.
    assert core["by_target"]["pattern"]["10"]["recall"] == 0.0
    assert core["by_target"]["strategy"]["10"]["recall"] > 0.0  # non-strawman


def test_pinned_baseline_core_is_self_consistent():
    # Post-S5 the baseline can no longer be recomputed (no matcher). Instead prove the pin
    # is tamper-evident: its stored result core hashes to its own recorded sha.
    pinned = json.loads(grade.BASELINE_OUT.read_text(encoding="utf-8"))
    sha = hashlib.sha256(_canon(pinned["RESULT_baseline"]).encode()).hexdigest()
    assert sha == pinned["result_core_sha256"]


def test_never_pooled():
    core = grade.load_pinned_baseline()
    # The pooled number exists ONLY under an explicit do-not-use key.
    assert "pooled_do_not_use" in core
    assert "recall" not in core  # no top-level pooled recall masquerading as the metric
    assert _gmetric()["stratification"]["policy"].lower().count("never") >= 1


# --------------------------------------------------------------------------- #
# Empty recognition -> NO_MATCH (the control problem recognises to nothing)
# --------------------------------------------------------------------------- #

def test_empty_recognition_recognizes_nothing():
    # The control problem P_EMPTY recognises to nothing (blank query + empty SHAPE).
    # The live-engine empty -> no_match envelope is proven in test_gmetric_s2.
    assert tr.recognize([""], []) == []
    assert tr.recognize([], []) == []


def test_control_problem_is_not_scored():
    reach = {r["problem"]: r for r in _gmetric()["reachable_set_map"]}
    assert reach["P_EMPTY"]["verdict"] == "X"
    assert reach["P_EMPTY"]["acceptable_ids"] == []


# --------------------------------------------------------------------------- #
# Blindness: SHAPE smuggles no gold; live recognizer == frozen snapshot
# --------------------------------------------------------------------------- #

def test_problem_language_shape_does_not_smuggle_the_gold():
    """A problem-language SHAPE must not contain the verbatim gold signal text -- that
    would gold-fit the baseline instead of measuring the register honestly."""
    reach = {r["problem"]: r for r in _gmetric()["reachable_set_map"]}
    gm = _gmetric()
    # rebuild text<-id so we can recover each gold's verbatim text
    ld = _loader()
    id2text = {}
    for kind in ("strategy", "pattern"):
        for row in tr.build_vocabulary(ld)[kind]:
            id2text[row["signal_id"]] = row["signal_text"].strip().lower()
    for p in build_gmetric_v1.PROBLEMS:
        if p["register"] != "problem_language":
            continue
        golds = {id2text[i] for i in reach[p["id"]]["acceptable_ids"]}
        shape_texts = {s.strip().lower() for s in tr.SHAPE.get(p["id"], [])}
        assert not (golds & shape_texts), f"{p['id']} SHAPE smuggles the gold text"


def test_live_recognizer_equals_frozen_snapshot():
    ld = _loader()
    live = tr.build_matches(ld)
    frozen = json.loads((GMETRIC / "themis_matches_v1.json").read_text(encoding="utf-8"))["matches"]
    assert live == frozen
    freeze = json.loads((GMETRIC / "themis_matches_freeze_v1.json").read_text(encoding="utf-8"))
    assert hashlib.sha256(_canon(live).encode()).hexdigest() == freeze["themis_matches_sha256"]


def test_recognizer_never_reads_the_answer_key():
    """Static proof: the recognizer references no gmetric FILE PATH (prose mentions ok).

    A degenerate/gold-fit recognizer would read the answer key; this one must not. We scan
    the AST for string literals that look like a filename (end in .json) and assert none
    names gmetric -- so a docstring may explain the collision while the code never opens it.
    """
    tree = ast.parse((GMETRIC / "themis_recognizer.py").read_text(encoding="utf-8"))
    path_literals = [n.value for n in ast.walk(tree)
                     if isinstance(n, ast.Constant) and isinstance(n.value, str)
                     and n.value.strip().endswith(".json")]
    assert path_literals == ["problems_blind_v1.json"]
    assert not any("gmetric" in lit for lit in path_literals)


# --------------------------------------------------------------------------- #
# The grader BITES a planted regression (built failing-first, directive 8)
# --------------------------------------------------------------------------- #
# Post-S5 the grader is exercised over the LIVE two-view engine (the matcher it once
# graded is deleted). Engine determinism across fresh loaders + PYTHONHASHSEED lives in
# test_gmetric_s2::TestDeterminismAndControl.

def test_grader_bites_planted_regression():
    """A retrieval that returns nothing must drop the non-strawman S-V stratum below the
    live engine's score -- proving the benchmark grader is not vacuous."""
    def broken(loader, query):
        return []

    good = grade.grade(eng.rank_engine, "good")["by_stratum"]["S-V"]["10"]["recall"]
    bad = grade.grade(broken, "broken")["by_stratum"]["S-V"]["10"]["recall"]
    assert good > 0.0          # the live engine answers the non-strawman stratum
    assert bad < good          # the grader bites when a method returns nothing


# --------------------------------------------------------------------------- #
# Fail-closed substrate trust root (CWE-345)
# --------------------------------------------------------------------------- #

def test_substrate_verifies_clean():
    checks = grade._verify_substrate()
    assert all(c["match"] for c in checks.values())
    assert set(checks) == set(grade._PINNED)


def test_substrate_fails_closed_on_drift(tmp_path, monkeypatch):
    bad = tmp_path / "freeze_manifest_bad.json"
    pins = {name: "0" * 64 for name in grade._PINNED}  # wrong hashes
    bad.write_text(json.dumps({"version": "v1", "pins": pins}), encoding="utf-8")
    monkeypatch.setattr(grade, "FREEZE_MANIFEST", bad)
    with pytest.raises(SystemExit, match="SUBSTRATE DRIFT"):
        grade._verify_substrate()


def test_substrate_fails_closed_on_pin_set_mismatch(tmp_path, monkeypatch):
    bad = tmp_path / "freeze_manifest_missing.json"
    bad.write_text(json.dumps({"version": "v1", "pins": {}}), encoding="utf-8")
    monkeypatch.setattr(grade, "FREEZE_MANIFEST", bad)
    with pytest.raises(SystemExit, match="pin set mismatch"):
        grade._verify_substrate()


def test_answer_key_hash_agrees_across_artifacts():
    g = _gmetric()
    b = json.loads((GMETRIC / "baseline_matcher_pinned_v1.json").read_text(encoding="utf-8"))
    assert g["answer_key_sha256"] == b["answer_key_sha256"]
    # Recompute the answer key from the frozen reach_map, trusting nothing.
    ak_core = sorted(
        ({"problem": r["problem"], "canonical": r["canonical"],
          "acceptable_ids": sorted(r["acceptable_ids"])}
         for r in g["reachable_set_map"] if r["verdict"] == "E"),
        key=lambda d: d["problem"])
    assert hashlib.sha256(_canon(ak_core).encode()).hexdigest() == g["answer_key_sha256"]


# --------------------------------------------------------------------------- #
# Locked legs -- set after the baseline
# --------------------------------------------------------------------------- #

def test_locked_legs_set_after_baseline():
    legs = json.loads((GMETRIC / "locked_legs_v1.json").read_text(encoding="utf-8"))
    assert legs["set_after_baseline"] is True
    pinned = grade.load_pinned_baseline()
    by_stratum = {s: v["10"]["recall"] for s, v in pinned["by_stratum"].items()}
    assert legs["baseline_snapshot"]["by_stratum_recall_at_10"] == by_stratum
    assert set(legs["legs"]) == {
        "LEG_1_no_regression", "LEG_2_strategy_problem_language_lift", "LEG_3_agent_pattern_reach"}


# --------------------------------------------------------------------------- #
# Import firewall
# --------------------------------------------------------------------------- #

def test_import_firewall_themis_only():
    forbidden = ("othrys", "coeus", "mnemos", "theia", "hyperion", "phoebe")
    for mod in ("themis_recognizer.py", "grade.py", "build_gmetric_v1.py", "set_locked_legs.py",
                "themis_engine_bench.py", "migrate_s2.py"):
        tree = ast.parse((GMETRIC / mod).read_text(encoding="utf-8"))
        names = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names += [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom):
                names.append(node.module or "")
        for n in names:
            root = n.split(".")[0]
            assert root not in forbidden, f"{mod} imports forbidden {n}"
