# Copyright (c) 2026 Reza Malik. Licensed under the Apache License, Version 2.0.
"""Deterministic grader for themis-Gmetric-v1 (story-350b3817, S0).

ONE grader (DRY). It grades ANY method_fn that maps a frozen query to a rank-ordered
list of recognition-vocabulary signal ids, against the frozen answer key in
gmetric_v1.json:

    A gold is COVERED@k iff its acceptable_ids intersect the method's top-k signal ids.
    recall@k = (# E-golds covered) / (# E-golds).  Only E golds are scored.

Every number is stratified by target / register / stratum -- NEVER a single pooled
mean (m-e8ccb163). The pooled recall is emitted only as ``pooled_do_not_use`` so a
reader cannot mistake it for the metric.

Determinism: grade runs with a FRESH KnowledgeLoader; the result core carries no
timestamp and is byte-identical across fresh loaders and any PYTHONHASHSEED.

Tamper-evidence (CWE-345): _verify_substrate reads its pins from the EXTERNAL
freeze_manifest_v1.json (the trust root), NEVER from gmetric_v1.json (which it grades
against), and fails closed on ANY drift -- gmetric included.

The legacy substring matcher that once produced the baseline (``rank_baseline`` over
``match_structural_signals``) was DELETED at S5; its baseline result core is permanently
frozen in baseline_matcher_pinned_v{VER}.json and read via ``load_pinned_baseline()`` --
never recomputed, because no matcher remains to run. The live retrieval engine is graded
by ``themis_engine_bench.rank_engine`` through this same ``grade`` (see test_gmetric_s2).

Firewall: imports only themis.* + the sibling recognizer (themis-only). No live DB.

Run (verify the substrate + report the pinned baseline):
    PYTHONPATH=F:/Repos/themis/src F:/Repos/othrys/.venv/Scripts/python.exe \
        tests/data/gmetric/grade.py
"""

from __future__ import annotations

import hashlib
import json
import os
from collections import defaultdict
from pathlib import Path

from themis.knowledge.loader import KnowledgeLoader

HERE = Path(__file__).resolve().parent
KDIR = Path(__file__).resolve().parents[3] / "src" / "themis" / "knowledge"
STRATEGIES_FILE, PATTERNS_FILE, RULES_FILE = (
    "test_strategies.json", "agent_patterns.json", "decision_rules.json")

# Corpus-freeze GENERATION selector (S2 re-freeze, council 25d9a8ea). The benchmark
# DATA (problems, golds, strata) is generation-invariant — only the corpus it freezes
# against moves: v1 = the S0 pre-fold substrate (RED gate, historical record); v2 = the
# post-fold substrate after decision_rules is dissolved onto the strategy corpus and the
# agent-pattern index is wired. Default "v1" preserves S0's provenance byte-for-byte;
# THEMIS_GMETRIC_VERSION=v2 resolves the re-frozen artifacts against the migrated corpus.
_VER = os.environ.get("THEMIS_GMETRIC_VERSION", "v1")

PROBLEMS_IN = HERE / f"problems_blind_{_VER}.json"
GMETRIC_IN = HERE / f"gmetric_{_VER}.json"
FREEZE_MANIFEST = HERE / f"freeze_manifest_{_VER}.json"
BASELINE_OUT = HERE / f"baseline_matcher_pinned_{_VER}.json"

KS = (10, 5)  # primary, secondary


def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha_path(p: Path) -> str:
    return sha_bytes(p.read_bytes())


def canonical_dump(obj) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


_PINNED = {
    PROBLEMS_IN.name: PROBLEMS_IN,
    GMETRIC_IN.name: GMETRIC_IN,
    STRATEGIES_FILE: KDIR / STRATEGIES_FILE,
    PATTERNS_FILE: KDIR / PATTERNS_FILE,
    RULES_FILE: KDIR / RULES_FILE,
}


def _verify_substrate() -> dict:
    """Prove the on-disk substrate == the frozen pins in the EXTERNAL manifest.

    Pins are read from freeze_manifest_v1.json -- NEVER from gmetric_v1.json, which holds
    the scored answer key and is therefore a certified artifact, not the certifier
    (reading its own pin from it would be circular trust, CWE-345). EVERY pinned file is
    hashed against the external manifest -- gmetric INCLUDED -- and ANY drift, a missing
    pin, or an unverified extra pin fails closed and INVALIDATES the metric.
    """
    if not FREEZE_MANIFEST.exists():
        raise SystemExit(f"MISSING FREEZE MANIFEST ({FREEZE_MANIFEST.name}); run "
                         "grade.py --refreeze after build_gmetric_v1.py.")
    pins = json.loads(FREEZE_MANIFEST.read_text(encoding="utf-8"))["pins"]
    missing = sorted(set(_PINNED) - set(pins))
    extra = sorted(set(pins) - set(_PINNED))
    if missing or extra:
        raise SystemExit(f"FREEZE MANIFEST pin set mismatch -- missing {missing}, "
                         f"unverified extra {extra}; metric INVALID.")
    checks = {name: {"cur": sha_path(p), "pin": pins[name]} for name, p in _PINNED.items()}
    for c in checks.values():
        c["match"] = c["cur"] == c["pin"]
    if not all(c["match"] for c in checks.values()):
        raise SystemExit("SUBSTRATE DRIFT -- on-disk hashes != frozen manifest pins; "
                         "metric INVALID.\n" + json.dumps(checks, indent=2))
    return checks


def grade(method_fn, method_name: str) -> dict:
    """Grade one method over the frozen benchmark. Fresh loader each call.

    Returns a deterministic result CORE (no timestamps) suitable for hashing.
    Stratified per target / register / stratum; pooled emitted only as pooled_do_not_use.
    """
    problems = {p["id"]: p for p in json.loads(PROBLEMS_IN.read_text(encoding="utf-8"))["problems"]}
    reach_map = json.loads(GMETRIC_IN.read_text(encoding="utf-8"))["reachable_set_map"]
    egolds = [r for r in reach_map if r["verdict"] == "E"]

    loader = KnowledgeLoader(knowledge_dir=KDIR)

    per_problem: dict[str, dict] = {}
    agg = {k: 0 for k in KS}
    denom = 0
    strat = {dim: defaultdict(lambda: {k: {"covered": 0, "of": 0} for k in KS})
             for dim in ("target", "register", "stratum")}

    for g in egolds:
        pid = g["problem"]
        prob = problems[pid]
        ranked = method_fn(loader, prob["query"])
        acc = set(g["acceptable_ids"])
        prow = {"stratum": g["stratum"], "n_acceptable": len(acc),
                "ranked_top10": ranked[:10], "grades": {}}
        for k in KS:
            tk = set(ranked[:k])
            hit = bool(acc & tk)
            prow["grades"][str(k)] = {"covered": int(hit)}
            for dim, key in (("target", g["target"]), ("register", g["register"]),
                             ("stratum", g["stratum"])):
                strat[dim][key][k]["of"] += 1
                if hit:
                    strat[dim][key][k]["covered"] += 1
            if hit:
                agg[k] += 1
        per_problem[pid] = prow
        denom += 1

    def _finalize(d):
        return {key: {str(k): {"covered": v[k]["covered"], "of": v[k]["of"],
                               "recall": round(v[k]["covered"] / v[k]["of"], 4) if v[k]["of"] else 0.0}
                      for k in KS}
                for key, v in sorted(d.items())}

    core = {
        "method": method_name,
        "denominator_E_golds": denom,
        "pooled_do_not_use": {str(k): round(agg[k] / denom, 4) if denom else 0.0 for k in KS},
        "by_target": _finalize(strat["target"]),
        "by_register": _finalize(strat["register"]),
        "by_stratum": _finalize(strat["stratum"]),
        "per_problem": {pid: per_problem[pid] for pid in sorted(per_problem)},
    }
    return core


def load_pinned_baseline() -> dict:
    """The FROZEN matcher-baseline result core, read from the pin.

    The legacy substring matcher (``match_structural_signals``) that produced this
    baseline was deleted at S5; the baseline is permanently frozen, so its per-problem
    and stratified grades are read from baseline_matcher_pinned_v{VER}.json -- never
    recomputed, because no matcher remains to run."""
    return json.loads(BASELINE_OUT.read_text(encoding="utf-8"))["RESULT_baseline"]


def main() -> None:
    """Verify the substrate and report the pinned baseline (read, never recomputed)."""
    _verify_substrate()
    pinned = json.loads(BASELINE_OUT.read_text(encoding="utf-8"))
    core = pinned["RESULT_baseline"]
    self_consistent = sha_bytes(canonical_dump(core).encode("utf-8")) == pinned["result_core_sha256"]
    print("substrate: VERIFIED")
    print("baseline result_core_sha256:", pinned["result_core_sha256"],
          "(self-consistent)" if self_consistent else "!= stored core (PIN CORRUPT)")
    print("by_stratum recall@10:",
          {s: v["10"]["recall"] for s, v in core["by_stratum"].items()})
    print("by_target recall@10:",
          {s: v["10"]["recall"] for s, v in core["by_target"].items()})
    print("pooled_do_not_use (flagged, NOT the metric):", core["pooled_do_not_use"])
    if not self_consistent:
        raise SystemExit("PIN CORRUPT -- stored baseline core != its own sha; metric INVALID.")


if __name__ == "__main__":
    main()
