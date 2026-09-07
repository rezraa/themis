# Copyright (c) 2026 Reza Malik. Licensed under the Apache License, Version 2.0.
"""Curated blind recognizer + recognition-vocabulary id space for themis-Gmetric
(story-350b3817, S0; council 25d9a8ea / m-6ce2dcc3; standard m-55f6d4da).

*** WHAT THIS MODULE IS. *** The blind, gold-blind recognition harness the benchmark
grades against: the recognition VOCABULARY (each strategy's own ``structural_signals``
+ each agent pattern's ``signals``) as a per-kind content-hash id space (``sig_id`` /
``build_vocabulary``), the curated per-problem SHAPE, the ``recognize`` step, and the
auditable {problem -> recognized phrases} record (``build_matches``). The engine bench
(themis_engine_bench.py) reuses this vocabulary + SHAPE so gold ids and reached ids come
from ONE definition.

*** THE PINNED MATCHER BASELINE. *** S0 froze a blind, stratified, per-stratum recall@10
baseline for the legacy substring matcher (``KnowledgeLoader.match_structural_signals``,
which indexed only the decision-rules table and left the strategy-own + agent-pattern
signals UNREACHABLE — the ceiling the benchmark exposed). That matcher was DELETED at S5
once the retrofit reached the corpus's own signals instead; its baseline result core is
permanently frozen in baseline_matcher_pinned_v2.json and read via
``grade.load_pinned_baseline()`` — never recomputed, because no matcher remains to run.
So this module no longer defines ``rank_baseline``.

*** WHY A CURATED SHAPE, AND WHY IT IS BLIND (Theia S0-FIX lesson, m-55f6d4da). ***
In production an agent reads a problem and names its structural signals, then passes
them to ``plan_test_strategy(structural_signals=[...])``. The benchmark cannot run an
LLM deterministically, so the SHAPE is its FROZEN, gold-blind stand-in. A DEGENERATE
recognizer (query tokens only) would structurally cap the problem-language register at 0
and measure the recognizer's poverty, not the path's -- the exact trap Theia's first S0
fell into. So each problem carries a curated SHAPE: a tester's restatement of the problem
in plausible structural-signal phrases, authored from the frozen problem/query ALONE,
NEVER from the gold answer key, and NEVER tuned toward gold after a result was seen (the
blind-curation gate). The auditable {problem -> recognized phrases} pairs are emitted into
themis_matches_v1.json for a reviewer to diff against the problem prose alone.

Firewall: imports only ``themis.*`` + stdlib. Reads only problems_blind + the loader's
live corpus; NEVER reads gmetric_*.json (the answer key). No live-DB access.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from themis.knowledge.loader import KnowledgeLoader

HERE = Path(__file__).resolve().parent
PROBLEMS_IN = HERE / "problems_blind_v1.json"


# --------------------------------------------------------------------------- #
# Signal-id space (ONE source of truth; imported by build_gmetric_v1 and the engine
# bench). A deterministic content hash SCOPED per owner-kind. Scoping by
# kind is the load-bearing property S0 hands S2: the four texts that appear in BOTH
# corpora (see the collision enumeration in gmetric_v1.json) would MERGE under a flat
# text-only hash, so a two-view accessor must key its ids per view. Here strategy and
# pattern signals never collide because the kind is folded into the hash.
# --------------------------------------------------------------------------- #
def sig_id(kind: str, text: str) -> str:
    """Deterministic per-kind content-hash signal id. ``kind`` in {strategy, pattern}."""
    return "sig-" + hashlib.sha256(f"{kind}|{text.strip().lower()}".encode()).hexdigest()[:12]


def build_vocabulary(loader: KnowledgeLoader) -> dict[str, list[dict]]:
    """The full recognition vocabulary as two labelled views, derived from the loader.

    ``{"strategy": [{signal_id, signal_text, owner_id}], "pattern": [...]}``. This is a
    harness-level preview of the nested two-view ``get_signal_index`` that S2 will file
    into the loader; S0 builds it here (corpus/ids held constant) so gold ids and reached
    ids are computed from ONE definition. Strategy signal texts are distinct (184/184) and
    pattern signal texts are distinct (60/60), so each signal id has a single owner within
    its kind.
    """
    strat: list[dict] = []
    for s in loader.get_all_strategies():
        for text in s.get("structural_signals", []):
            strat.append({"signal_id": sig_id("strategy", text), "signal_text": text,
                          "owner_id": s["id"]})
    pat: list[dict] = []
    for p in loader.get_all_agent_patterns():
        for text in p.get("signals", []):
            pat.append({"signal_id": sig_id("pattern", text), "signal_text": text,
                        "owner_id": p["id"]})
    return {"strategy": strat, "pattern": pat}


# --------------------------------------------------------------------------- #
# SHAPE: the recogniser's working memory, keyed by problem id. Each value is a list
# of plausible structural-signal phrases a tester would name from that problem's prose
# ALONE (gold-blind: no gmetric read, no corpus id copied verbatim to fit gold). For
# verbatim-register problems the query already IS a catalogued signal, so SHAPE is a
# light backup; for problem-language problems SHAPE is the bridge the register needs so
# the miss that remains is the substring matcher's, not the recognizer's.
# --------------------------------------------------------------------------- #
SHAPE: dict[str, list[str]] = {
    # ---- S-V: STRATEGY, verbatim (query IS a strategy structural_signal). ----
    "P01": ["parameterized cases", "many input variations"],
    "P02": ["isolated unit under test", "known inputs and outputs"],
    "P03": ["deterministic pure logic", "no external dependencies"],
    "P04": ["http endpoint", "request response cycle"],
    "P05": ["rendered component output", "snapshot of the view"],
    "P06": ["throttling and quotas", "429 handling"],
    "P07": ["dependency injection seam", "swap collaborators for doubles"],
    "P08": ["edge and boundary values", "off by one ranges"],
    "P09": ["rollback on failure", "database transaction integrity"],
    "P10": ["retry-safe writes", "duplicate request suppression"],
    # ---- S-PL: STRATEGY, problem-language (paraphrase). ----
    "P11": ["asynchronous code", "concurrency and race conditions", "await and timeouts"],
    "P12": ["repository talks to a real database", "sql query bugs mocks miss"],
    "P13": ["revenue critical user flow", "money path must not break"],
    "P14": ["encode then decode", "random inputs preserve data"],
    "P15": ["memory grows over days", "long running process degradation"],
    "P16": ["third party packages", "known vulnerability alerts"],
    "P17": ["services owned by different teams", "deploys break downstream callers"],
    "P18": ["coverage high confidence low", "do the tests catch real bugs"],
    "P19": ["layout shifted after a css change", "visual regression"],
    "P20": ["public site accessibility", "contrast and aria compliance"],
    # ---- P-V: AGENT-PATTERN, verbatim (query IS an agent-pattern signal). ----
    "P21": ["prompt changed", "output quality drifted"],
    "P22": ["function calling", "tool selection and parameters"],
    "P23": ["retrieval augmented answers", "grounded in source documents"],
    "P24": ["user facing assistant", "abuse and content policy"],
    "P25": ["very long chats", "history near the window limit"],
    "P26": ["stable outputs in a pipeline", "variance across runs"],
    "P27": ["streamed tokens", "server sent events chunks"],
    "P28": ["fabricated citations", "made up source urls"],
    # ---- P-PL: AGENT-PATTERN, problem-language (paraphrase). ----
    "P29": ["tweaking the system prompt", "answer quality shifts silently"],
    "P30": ["agent calls the wrong tool", "garbage arguments extracted"],
    "P31": ["assistant forgets earlier turns", "contradicts itself in a long chat"],
    "P32": ["bot invents facts", "claims not in the provided documents"],
    "P33": ["jailbreaking the assistant", "coax it into harmful output"],
    "P34": ["stuffing many retrieved docs", "prompt silently truncates"],
    "P35": ["response times crept up", "need p95 latency baselines"],
    "P36": ["research agent feeds a writer agent", "errors corrupt the next stage"],
    # ---- control: empty recognition -> NO_MATCH. ----
    "P_EMPTY": [],
}


# --------------------------------------------------------------------------- #
# Recognition.
# --------------------------------------------------------------------------- #

def _load_problems() -> list[dict]:
    return json.loads(PROBLEMS_IN.read_text(encoding="utf-8"))["problems"]


def _query_to_pid() -> dict[tuple[str, ...], str]:
    return {tuple(p["query"]): p["id"] for p in _load_problems()}


def recognize(query: list[str], shape: list[str]) -> list[str]:
    """Recognise the structural-signal phrases for one problem. Deterministic, gold-blind.

    The recogniser's whole job is to name plausible structural signals a tester would
    hand ``plan_test_strategy``: the frozen query strings UNION the curated SHAPE phrases,
    de-duplicated, order-stable (query first, then SHAPE). It reads only its arguments --
    never the gold answer key. Empty query and empty SHAPE -> ``[]`` (the NO_MATCH leg).
    """
    out: list[str] = []
    seen: set[str] = set()
    for phrase in list(query) + list(shape):
        key = phrase.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(phrase)
    return out


def build_matches(loader: KnowledgeLoader) -> dict[str, list[str]]:
    """{pid: recognised phrases} for every problem -- the auditable blind-curation record.

    Pure function of (problems_blind, SHAPE). Emitted to themis_matches_v1.json and proven
    live == frozen by the S0 test. Reads no gold answer key.
    """
    return {p["id"]: recognize(p["query"], SHAPE.get(p["id"], [])) for p in _load_problems()}
