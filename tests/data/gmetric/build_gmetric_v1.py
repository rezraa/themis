# Copyright (c) 2026 Reza Malik. Licensed under the Apache License, Version 2.0.
"""Authoring + provenance for themis-Gmetric-v1 (story-350b3817, S0).

Emits the byte-frozen benchmark artifacts from ONE source of truth (the authored
PROBLEMS below): problems_blind_v1.json (blind data, no golds), gmetric_v1.json (the
scored answer key + the three denominators + the collision enumeration), and the
recognizer snapshot (themis_matches_v1.json + its trust root themis_matches_freeze_v1).

THREE DENOMINATORS, never conflated (Mnemos discipline, m-0364c120):
  1. recall denominator            -- the E-golds in the benchmark (scored by grade.py).
  2. reachable vocabulary          -- METHOD-INDEPENDENT: every strategy structural_signal
                                      (184) + every agent-pattern signal (60) = 244. What a
                                      correct retrieval path SHOULD be able to reach.
  3. matcher-reachable ceiling     -- METHOD-DEPENDENT: how many of those 244 signals are
                                      even substring-reachable through the 45-rule index the
                                      baseline uses. This is the ceiling the baseline path
                                      can EVER hit, measured independently of any recognizer
                                      -- so a near-zero pattern stratum is provably the
                                      PATH's poverty, not the benchmark's.

Blindness: SHAPE (in themis_recognizer) is authored from the problem prose alone and is
never tuned toward these golds; the answer key here is authored from which strategy/pattern
each problem is genuinely ABOUT. The two are frozen separately; the S0 test asserts no
acceptable_id text is smuggled into SHAPE.

Firewall: themis.* + stdlib only. No live-DB access.
Pipeline order: build_gmetric_v1.py -> grade.py --refreeze -> set_locked_legs.py.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from themis.knowledge.loader import KnowledgeLoader
from themis_recognizer import build_matches, build_vocabulary, sig_id

HERE = Path(__file__).resolve().parent
KDIR = Path(__file__).resolve().parents[3] / "src" / "themis" / "knowledge"

# Corpus-freeze GENERATION (see grade._VER). The authored PROBLEMS/golds/strata are
# generation-invariant; only the corpus they freeze against moves. Default v1 preserves
# S0's provenance; THEMIS_GMETRIC_VERSION=v2 re-emits against the post-fold corpus
# (same golds -> identical answer_key_sha256; denominator/ceiling/collisions recomputed).
_VER = os.environ.get("THEMIS_GMETRIC_VERSION", "v1")

PROBLEMS_OUT = HERE / f"problems_blind_{_VER}.json"
GMETRIC_OUT = HERE / f"gmetric_{_VER}.json"
MATCHES_OUT = HERE / f"themis_matches_{_VER}.json"
MATCHES_FREEZE_OUT = HERE / f"themis_matches_freeze_{_VER}.json"


def canonical_dump(obj) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=True) + "\n"


def sha_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- #
# THE AUTHORED BLIND PROBLEMS (source of truth). Each: id, target (strategy|pattern),
# register (verbatim|problem_language|control), query (what an agent receives), problem
# (auditor prose), gold_texts (VERBATIM corpus signal texts), verdict (E scored / X not).
# stratum = f"{S|P}-{V|PL}". Verbatim queries ARE catalogued corpus signal texts; the
# problem-language queries are paraphrases a real user would write.
# --------------------------------------------------------------------------- #
PROBLEMS: list[dict] = [
    # ===== S-V: STRATEGY, verbatim (query IS a strategy structural_signal) =====
    # Six drawn from the substring-reachable 16 (non-strawman: the matcher answers its
    # own rule-idiom) and four from the unreachable 168 (the ceiling, verbatim yet unseen).
    dict(id="P01", target="strategy", register="verbatim", verdict="E",
         query=["function with many edge cases on same signature"],
         problem="A single function signature has a large set of edge cases to cover.",
         gold_texts=["function with many edge cases on same signature"]),
    dict(id="P02", target="strategy", register="verbatim", verdict="E",
         query=["testing isolated function logic with known inputs"],
         problem="Isolated function logic is tested with a set of known inputs.",
         gold_texts=["testing isolated function logic with known inputs"]),
    dict(id="P03", target="strategy", register="verbatim", verdict="E",
         query=["pure function with no side effects"],
         problem="A pure function with no side effects is the unit under test.",
         gold_texts=["pure function with no side effects"]),
    dict(id="P04", target="strategy", register="verbatim", verdict="E",
         query=["REST or GraphQL endpoint"],
         problem="A REST or GraphQL endpoint must be exercised over the wire.",
         gold_texts=["REST or GraphQL endpoint"]),
    dict(id="P05", target="strategy", register="verbatim", verdict="E",
         query=["UI component rendering"],
         problem="A UI component's rendered output must stay stable.",
         gold_texts=["UI component rendering"]),
    dict(id="P06", target="strategy", register="verbatim", verdict="E",
         query=["rate-limited API endpoint"],
         problem="A rate-limited API endpoint enforces per-caller quotas.",
         gold_texts=["rate-limited API endpoint"]),
    dict(id="P07", target="strategy", register="verbatim", verdict="E",
         query=["method with injectable dependencies"],
         problem="A method's collaborators are injected and can be replaced with doubles.",
         gold_texts=["method with injectable dependencies"]),
    dict(id="P08", target="strategy", register="verbatim", verdict="E",
         query=["boundary value analysis needed"],
         problem="Boundary value analysis is required across an input range.",
         gold_texts=["boundary value analysis needed"]),
    dict(id="P09", target="strategy", register="verbatim", verdict="E",
         query=["transaction rollback behavior"],
         problem="Database transaction rollback behaviour must be verified.",
         gold_texts=["transaction rollback behavior"]),
    dict(id="P10", target="strategy", register="verbatim", verdict="E",
         query=["idempotency key handling"],
         problem="An endpoint handles idempotency keys for retry-safe writes.",
         gold_texts=["idempotency key handling"]),

    # ===== S-PL: STRATEGY, problem-language (paraphrase) =====
    dict(id="P11", target="strategy", register="problem_language", verdict="E",
         query=["we have code that uses async and await and we're worried about race conditions and timeouts"],
         problem="Async/await code with race-condition and timeout concerns (-> unit_async).",
         gold_texts=["async function or coroutine"]),
    dict(id="P12", target="strategy", register="problem_language", verdict="E",
         query=["our repository layer talks to postgres and we keep shipping query bugs mocks don't catch"],
         problem="Repository layer against a real database, query bugs mocks miss (-> integration_database).",
         gold_texts=["ORM or raw SQL queries"]),
    dict(id="P13", target="strategy", register="problem_language", verdict="E",
         query=["the checkout and payment path cannot break it's how we make money"],
         problem="Revenue-critical checkout/payment path (-> e2e_critical_path).",
         gold_texts=["checkout or payment flow"]),
    dict(id="P14", target="strategy", register="problem_language", verdict="E",
         query=["we encode and decode messages and want to be sure round-tripping never loses data across random inputs"],
         problem="Encode/decode round-trip must hold across random inputs (-> property_based_fuzzing).",
         gold_texts=["serialization roundtrip"]),
    dict(id="P15", target="strategy", register="problem_language", verdict="E",
         query=["the service runs for days and memory slowly climbs until it falls over"],
         problem="Long-running service with a suspected slow memory leak (-> load_soak).",
         gold_texts=["suspected memory leak"]),
    dict(id="P16", target="strategy", register="problem_language", verdict="E",
         query=["we pull in a lot of third-party packages and need to know when one has a known vulnerability"],
         problem="Third-party dependencies needing CVE monitoring (-> security_dependency_scan).",
         gold_texts=["CVE monitoring for dependencies"]),
    dict(id="P17", target="strategy", register="problem_language", verdict="E",
         query=["several teams own services that call each other and deploys keep breaking downstream consumers"],
         problem="Independently-deployed microservices breaking consumers (-> contract_consumer_driven).",
         gold_texts=["microservice consuming another service API"]),
    dict(id="P18", target="strategy", register="problem_language", verdict="E",
         query=["coverage is high but we don't trust the tests actually catch regressions"],
         problem="High coverage, low confidence the tests catch bugs (-> mutation_first_order).",
         gold_texts=["verifying tests actually catch bugs"]),
    dict(id="P19", target="strategy", register="problem_language", verdict="E",
         query=["a css refactor silently shifted the layout and no functional test noticed"],
         problem="CSS refactor caused an unnoticed visual/layout regression (-> visual_pixel_diff).",
         gold_texts=["CSS refactoring affecting layout"]),
    dict(id="P20", target="strategy", register="problem_language", verdict="E",
         query=["legal says the public site must meet accessibility contrast and aria requirements"],
         problem="Public site must meet WCAG contrast/ARIA rules (-> accessibility_wcag_aa).",
         gold_texts=["WCAG compliance requirement"]),

    # ===== P-V: AGENT-PATTERN, verbatim (query IS an agent_pattern signal) =====
    # P23-P26 are the FOUR collision texts (also strategy signals): they prove the baseline
    # never surfaces the PATTERN even for a text it shares with a strategy.
    dict(id="P21", target="pattern", register="verbatim", verdict="E",
         query=["system prompt was modified"],
         problem="A system prompt was modified and output may have drifted.",
         gold_texts=["system prompt was modified"]),
    dict(id="P22", target="pattern", register="verbatim", verdict="E",
         query=["agent has access to multiple tools"],
         problem="An agent has access to multiple tools and must pick correctly.",
         gold_texts=["agent has access to multiple tools"]),
    dict(id="P23", target="pattern", register="verbatim", verdict="E",
         query=["RAG-based agent with source documents"],
         problem="A RAG-based agent answers from source documents (collision text).",
         gold_texts=["RAG-based agent with source documents"]),
    dict(id="P24", target="pattern", register="verbatim", verdict="E",
         query=["public-facing AI agent"],
         problem="A public-facing AI agent must resist abuse (collision + substring-reachable).",
         gold_texts=["public-facing AI agent"]),
    dict(id="P25", target="pattern", register="verbatim", verdict="E",
         query=["long conversation sessions"],
         problem="Long conversation sessions approach the context window (collision text).",
         gold_texts=["long conversation sessions"]),
    dict(id="P26", target="pattern", register="verbatim", verdict="E",
         query=["production reliability requirement"],
         problem="A production reliability requirement demands output determinism (collision text).",
         gold_texts=["production reliability requirement"]),
    dict(id="P27", target="pattern", register="verbatim", verdict="E",
         query=["agent uses server-sent events"],
         problem="An agent streams responses via server-sent events.",
         gold_texts=["agent uses server-sent events"]),
    dict(id="P28", target="pattern", register="verbatim", verdict="E",
         query=["agent invents citations or URLs"],
         problem="An agent invents citations or URLs that do not exist.",
         gold_texts=["agent invents citations or URLs"]),

    # ===== P-PL: AGENT-PATTERN, problem-language (paraphrase) =====
    dict(id="P29", target="pattern", register="problem_language", verdict="E",
         query=["every time we tweak the system prompt the answer quality changes and we don't catch it"],
         problem="Prompt tweaks silently shift answer quality (-> prompt_regression).",
         gold_texts=["system prompt was modified"]),
    dict(id="P30", target="pattern", register="problem_language", verdict="E",
         query=["the agent keeps calling the wrong function or passing garbage arguments"],
         problem="Agent selects wrong tools / bad params (-> tool_call_validation).",
         gold_texts=["agent has access to multiple tools"]),
    dict(id="P31", target="pattern", register="problem_language", verdict="E",
         query=["in a long chat the assistant forgets what the user said earlier and contradicts itself"],
         problem="Assistant loses context and self-contradicts (-> multi_turn_consistency).",
         gold_texts=["agent contradicts earlier statements"]),
    dict(id="P32", target="pattern", register="problem_language", verdict="E",
         query=["the bot invents facts that aren't in the documents we gave it"],
         problem="Bot fabricates facts not grounded in context (-> hallucination_detection).",
         gold_texts=["agent makes factual claims"]),
    dict(id="P33", target="pattern", register="problem_language", verdict="E",
         query=["people are jailbreaking our public assistant to make it say harmful things"],
         problem="Public assistant is being jailbroken (-> safety_guardrail).",
         gold_texts=["jailbreak attempts in production logs"]),
    dict(id="P34", target="pattern", register="problem_language", verdict="E",
         query=["we stuff a lot of retrieved docs into the prompt and sometimes it silently truncates"],
         problem="Large context injection silently truncates (-> token_budget).",
         gold_texts=["large context injection in prompts"]),
    dict(id="P35", target="pattern", register="problem_language", verdict="E",
         query=["response times crept up after a model change and we need p95 baselines"],
         problem="Latency regressed after a model change (-> latency_profiling).",
         gold_texts=["agent has response time SLAs"]),
    dict(id="P36", target="pattern", register="problem_language", verdict="E",
         query=["we chain a research agent into a writer agent and errors in the first corrupt the second"],
         problem="Chained agents where a stage's error corrupts downstream (-> agent_chain_integrity).",
         gold_texts=["multiple agents chained in sequence"]),

    # ===== control: empty recognition -> NO_MATCH (verdict X, never scored) =====
    dict(id="P_EMPTY", target="none", register="control", verdict="X",
         query=[""],
         problem="Empty query: recognition yields nothing; the path must resolve to NO_MATCH.",
         gold_texts=[]),
]


def _stratum(p: dict) -> str:
    if p["register"] == "control":
        return "CONTROL"
    t = "S" if p["target"] == "strategy" else "P"
    r = "V" if p["register"] == "verbatim" else "PL"
    return f"{t}-{r}"


def main() -> None:
    loader = KnowledgeLoader(knowledge_dir=KDIR)
    vocab = build_vocabulary(loader)

    # Verify every gold text is a VERBATIM corpus signal of the declared kind.
    strat_texts = {r["signal_text"].strip().lower(): r for r in vocab["strategy"]}
    pat_texts = {r["signal_text"].strip().lower(): r for r in vocab["pattern"]}
    for p in PROBLEMS:
        for gt in p["gold_texts"]:
            table = strat_texts if p["target"] == "strategy" else pat_texts
            if gt.strip().lower() not in table:
                raise SystemExit(f"{p['id']}: gold text not a verbatim {p['target']} signal: {gt!r}")

    # ---- problems_blind (no golds) ----
    problems_blind = {
        "version": "v1",
        "story": "story-350b3817",
        "problems": [
            {"id": p["id"], "target": p["target"], "register": p["register"],
             "stratum": _stratum(p), "query": p["query"], "problem": p["problem"]}
            for p in PROBLEMS
        ],
    }
    # Written first: the recognizer's build_matches reads problems_blind from disk.
    PROBLEMS_OUT.write_text(canonical_dump(problems_blind), encoding="utf-8")

    # ---- reachable_set_map (the scored answer key) ----
    reach_map = []
    for p in PROBLEMS:
        kind = p["target"]
        acc = sorted({sig_id(kind, gt) for gt in p["gold_texts"]}) if p["gold_texts"] else []
        canonical = " + ".join(f"{(strat_texts if kind=='strategy' else pat_texts)[gt.strip().lower()]['owner_id']}:{gt}"
                               for gt in p["gold_texts"]) if p["gold_texts"] else "(none)"
        reach_map.append({
            "problem": p["id"], "canonical": canonical, "target": p["target"],
            "register": p["register"], "stratum": _stratum(p), "verdict": p["verdict"],
            "acceptable_ids": acc,
        })

    # ---- reachable vocabulary denominator (method-independent) ----
    reachable_denominator = {
        "note": "The full recognition vocabulary that a correct path SHOULD reach. "
                "frameworks.json EXCLUDED (a lookup/hydration dimension, not a recognition corpus).",
        "strategy_signals": len(vocab["strategy"]),
        "pattern_signals": len(vocab["pattern"]),
        "total": len(vocab["strategy"]) + len(vocab["pattern"]),
    }

    # ---- matcher-reachable ceiling (method-dependent, static; the premise crux) ----
    # The decision-rules table is read straight from the frozen substrate FILE: the loader
    # stopped loading it at S5 (matcher deleted), but the file is kept sha-pinned, and this
    # historical S0 ceiling is computed from the same rule signals it always was.
    _rules_on_disk = json.loads((KDIR / "decision_rules.json").read_text(encoding="utf-8"))["rules"]
    rule_sigs = sorted({r.get("structural_signal", "").strip().lower()
                        for r in _rules_on_disk if r.get("structural_signal")})

    def reachable_through_rules(text: str) -> bool:
        t = text.strip().lower()
        return any(t in r or r in t for r in rule_sigs)

    strat_reach = sorted(r["signal_text"] for r in vocab["strategy"]
                         if reachable_through_rules(r["signal_text"]))
    pat_reach = sorted(r["signal_text"] for r in vocab["pattern"]
                       if reachable_through_rules(r["signal_text"]))
    matcher_reachable_ceiling = {
        "note": "How many vocabulary signals are even bidirectional-substring-reachable "
                "through the 45 decision_rules signals the baseline indexes. Measured "
                "independently of any recognizer -- so the near-zero pattern reach is the "
                "PATH's, not the benchmark's. NB even a 'reachable' pattern signal routes "
                "to a STRATEGY, never back to its pattern node, so baseline pattern recall "
                "is 0 regardless.",
        "rule_signals_indexed": len(rule_sigs),
        "strategy_signals_reachable": len(strat_reach),
        "strategy_signals_total": len(vocab["strategy"]),
        "pattern_signals_reachable": len(pat_reach),
        "pattern_signals_total": len(vocab["pattern"]),
        "strategy_reachable_texts": strat_reach,
        "pattern_reachable_texts": pat_reach,
    }

    # ---- id-space collision enumeration (feeds the S2 nested-view decision) ----
    strat_only_texts = {r["signal_text"].strip().lower() for r in vocab["strategy"]}
    pat_only_texts = {r["signal_text"].strip().lower() for r in vocab["pattern"]}
    collision_texts = sorted(strat_only_texts & pat_only_texts)
    # Under a flat text-only hash the colliding texts would MERGE; under the per-kind hash
    # used here they do not. Prove both.
    flat_ids = {}
    per_kind_collisions = 0
    for t in collision_texts:
        flat = "sig-" + hashlib.sha256(t.encode()).hexdigest()[:12]
        flat_ids[t] = flat
        if sig_id("strategy", t) == sig_id("pattern", t):
            per_kind_collisions += 1
    collisions = {
        "note": "Does any strategy structural_signal TEXT equal any agent_pattern signal "
                "TEXT? NON-ZERO here (Theia's was 0), so a flat text-only signal-id space "
                "would MERGE these across the two corpora -- which is exactly why S2's "
                "get_signal_index must be a NESTED two-view keyed per view (m-5a5837da). "
                "The per-kind hash used by this benchmark already keeps them distinct.",
        "collision_count": len(collision_texts),
        "collision_texts": collision_texts,
        "flat_text_hash_would_collide": len(collision_texts),
        "per_kind_hash_collisions": per_kind_collisions,
    }

    # ---- answer key hash (over the E-scored rows only; content-bound) ----
    ak_core = sorted(
        ({"problem": r["problem"], "canonical": r["canonical"],
          "acceptable_ids": sorted(r["acceptable_ids"])}
         for r in reach_map if r["verdict"] == "E"),
        key=lambda d: d["problem"],
    )
    answer_key_sha256 = sha_text(canonical_dump(ak_core))

    gmetric = {
        "version": "v1",
        "story": "story-350b3817",
        "council": "25d9a8ea / m-6ce2dcc3",
        "standard": "m-55f6d4da",
        "reachable_denominator": reachable_denominator,
        "matcher_reachable_ceiling": matcher_reachable_ceiling,
        "collisions": collisions,
        "stratification": {
            "dims": ["target", "register", "stratum"],
            "strata": ["S-V", "S-PL", "P-V", "P-PL"],
            "policy": "PER STRATUM, never a pooled mean (m-e8ccb163). The pooled recall is "
                      "emitted by grade.py only as pooled_do_not_use.",
        },
        "reachable_set_map": reach_map,
        "answer_key_sha256": answer_key_sha256,
    }

    # ---- recognizer snapshot (auditable blind-curation record) + trust root ----
    matches = build_matches(loader)
    matches_doc = {"version": "v1", "matches": matches}
    matches_sha = sha_text(canonical_dump(matches))
    matches_freeze = {"version": "v1", "themis_matches_sha256": matches_sha}

    GMETRIC_OUT.write_text(canonical_dump(gmetric), encoding="utf-8")
    MATCHES_OUT.write_text(canonical_dump(matches_doc), encoding="utf-8")
    MATCHES_FREEZE_OUT.write_text(canonical_dump(matches_freeze), encoding="utf-8")

    print("wrote:", PROBLEMS_OUT.name, GMETRIC_OUT.name, MATCHES_OUT.name, MATCHES_FREEZE_OUT.name)
    print("problems:", len(PROBLEMS), "E-golds:", sum(1 for r in reach_map if r["verdict"] == "E"))
    print("reachable_denominator:", reachable_denominator["total"],
          f"({reachable_denominator['strategy_signals']} strat + {reachable_denominator['pattern_signals']} pat)")
    print("matcher-reachable ceiling: strat",
          f"{matcher_reachable_ceiling['strategy_signals_reachable']}/{len(vocab['strategy'])}",
          "pat", f"{matcher_reachable_ceiling['pattern_signals_reachable']}/{len(vocab['pattern'])}")
    print("collisions:", collisions["collision_count"], collision_texts)
    print("answer_key_sha256:", answer_key_sha256)


if __name__ == "__main__":
    main()
