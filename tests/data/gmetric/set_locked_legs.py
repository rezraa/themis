# Copyright (c) 2026 Reza Malik. Licensed under the Apache License, Version 2.0.
"""Set the THREE locked legs for themis-Gmetric-v1 (story-350b3817, S0).

The legs are S1's bar. They are set AFTER the pinned baseline is read (the discipline:
never calibrate a leg against a number you have not yet measured) and carry the
baseline snapshot so a reviewer can prove they were set after, not fitted before. S0
does NOT run any engine -- it sets the bar the S1 engine must clear on the SAME frozen
problems/golds/strata.

LEG_1  NO-REGRESSION (the collapse LOCK, m-e8ccb163): the engine's recall@10 >= the
       baseline's on EVERY stratum, with a one-sided-gain inspection so a lift in one
       stratum cannot mask a loss in another.
LEG_2  STRATEGY problem-language lift: S-PL recall@10(engine) >= baseline + 0.30 -- the
       paraphrase register the substring matcher structurally cannot serve (baseline 0.0).
LEG_3  AGENT-PATTERN reach: pattern-target recall@10(engine) >= 0.40 -- the entire
       agent_patterns corpus the matcher has no route to (baseline 0.0).

Binding invariants (not numeric, still gates): determinism byte-identical across fresh
loaders + PYTHONHASHSEED; empty matched ids -> NO_MATCH on every arm.

Run after grade.py --refreeze:
    PYTHONPATH=F:/Repos/themis/src F:/Repos/othrys/.venv/Scripts/python.exe \
        tests/data/gmetric/set_locked_legs.py
"""

from __future__ import annotations

import json
from pathlib import Path

import grade

HERE = Path(__file__).resolve().parent
LEGS_OUT = HERE / "locked_legs_v1.json"


def main() -> None:
    baseline = grade.load_pinned_baseline()
    by_stratum = {s: v["10"]["recall"] for s, v in baseline["by_stratum"].items()}
    by_target = {s: v["10"]["recall"] for s, v in baseline["by_target"].items()}

    legs = {
        "version": "v1",
        "story": "story-350b3817",
        "set_after_baseline": True,
        "baseline_snapshot": {"by_stratum_recall_at_10": by_stratum,
                              "by_target_recall_at_10": by_target},
        "legs": {
            "LEG_1_no_regression": {
                "rule": "engine recall@10 >= baseline recall@10 on EVERY stratum",
                "baseline_by_stratum": by_stratum,
                "one_sided_gain_inspection": True,
            },
            "LEG_2_strategy_problem_language_lift": {
                "rule": "S-PL recall@10(engine) - baseline >= 0.30",
                "baseline": by_stratum.get("S-PL", 0.0),
                "min_delta": 0.30,
            },
            "LEG_3_agent_pattern_reach": {
                "rule": "pattern-target recall@10(engine) >= 0.40",
                "baseline": by_target.get("pattern", 0.0),
                "floor": 0.40,
            },
        },
        "invariants": [
            "result_core_sha256 byte-identical across 3 fresh loaders + PYTHONHASHSEED flip",
            "empty matched_signal_ids -> NO_MATCH on every arm (baseline proven at S0)",
            "answer key byte-frozen; --refreeze the sole mutation path (CWE-345 fail-closed)",
        ],
    }
    LEGS_OUT.write_text(json.dumps(legs, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
                        encoding="utf-8")
    print("wrote:", LEGS_OUT.name)
    print("baseline by_stratum recall@10:", by_stratum)


if __name__ == "__main__":
    main()
