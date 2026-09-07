# Copyright (c) 2026 Reza Malik. Licensed under the Apache License, Version 2.0.
"""S2 corpus migration: dissolve Themis ``decision_rules`` onto the strategy corpus
and cross-link the agent views (story-6c63a3bd, council 25d9a8ea / m-6ce2dcc3).

TWO edits, both content-POSITIVE and idempotent (mirrors the mnemos migrate_s2
COPY-not-move contract, b781d576-decision-2):

  1. FOLD  -- COPY each rule's ``structural_signal`` onto its ``recommended_strategy``'s
     ``structural_signals`` where ABSENT (dedup-then-append). decision_rules.json is
     KEPT byte-for-byte so ``match_structural_signals`` stays callable and the pinned
     baseline is preserved; the transitional coexistence (rule key + folded index text)
     is the blessed tranche norm, removed WITH the matcher at S5 -- NOT a DRY breach,
     because the one-source-of-truth is the epic END-state (S5). This RAISES
     reachability: the rule problem-idiom phrasings, previously indexed only by the
     substring matcher, now live on the strategy the rule recommends, so the Shape-C
     engine reaches them by construction.

  2. CROSS-LINK -- add an ``agent_pattern`` reference (by EXISTING pattern id) to each
     of the 12 agent-category strategies that twin an ``agent_patterns.json`` pattern,
     so ``get_signal_index``'s two views REFERENCE rather than DUPLICATE the shared
     agent concept (Coeus DRY guard: cross-link only, never copy knowledge between the
     views). No new content/text is authored -- only a reference by id.

Provenance (AC): the rule-by-rule fold plan (which rule signal went onto which strategy,
and whether it was already present) is written to ``docs/migration_proofs.md`` and
returned by :func:`fold_plan` for the test to verify dedup rule-by-rule.

Byte-preserving: the corpus uses CRLF, 2-space indent, ``ensure_ascii=False`` and INLINE
``complexity`` objects, so a full re-serialize would reformat every line. Like the mnemos
mirror this does LINE-SURGICAL edits -- it rebuilds only the ``structural_signals`` block
of each folded strategy and inserts one ``agent_pattern`` line after each agent strategy's
``category`` line; every other byte (inline objects included) passes through untouched.
``json.loads`` validates the surgery before the write.

Firewall: imports only stdlib; reads/writes only the on-disk themis corpus (no
othrys.*/coeus.*/mnemos.*/theia.* import, no DB).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

KDIR = Path(__file__).resolve().parents[3] / "src" / "themis" / "knowledge"
STRATEGIES = KDIR / "test_strategies.json"
RULES = KDIR / "decision_rules.json"
PATTERNS = KDIR / "agent_patterns.json"
PROOFS = Path(__file__).resolve().parents[3] / "docs" / "migration_proofs.md"

# The 12 agent-category strategy <-> agent_patterns twin map (same concept, different
# id). Authored (the names differ: agent_chain<->agent_chain_integrity,
# agent_safety<->safety_guardrail, agent_multi_turn<->multi_turn_consistency, ...), so it
# cannot be derived mechanically; each value is an EXISTING agent_patterns.json id.
AGENT_XLINK: dict[str, str] = {
    "agent_prompt_regression": "prompt_regression",
    "agent_tool_call_validation": "tool_call_validation",
    "agent_multi_turn": "multi_turn_consistency",
    "agent_hallucination": "hallucination_detection",
    "agent_determinism": "determinism",
    "agent_token_budget": "token_budget",
    "agent_safety": "safety_guardrail",
    "agent_chain": "agent_chain_integrity",
    "agent_stream_validation": "stream_validation",
    "agent_latency_profiling": "latency_profiling",
    "agent_context_window": "context_window_management",
    "agent_grounding": "grounding_accuracy",
}


def fold_plan(strategies: list[dict], rules: list[dict]) -> list[dict]:
    """The rule-by-rule fold plan (pure, no I/O) -- the provenance record.

    For each rule: which strategy its ``structural_signal`` folds onto and whether that
    signal is ALREADY present there (dedup). ``status`` is ``present`` (a no-op dedup) or
    ``append`` (content-positive add). Deterministic, file-order.
    """
    by_id = {s["id"]: s for s in strategies}
    plan: list[dict] = []
    for r in rules:
        sig = r["structural_signal"].strip()
        rs = r["recommended_strategy"]
        strat = by_id.get(rs)
        if strat is None:
            plan.append({"rule": r["id"], "signal": sig, "strategy": rs,
                         "status": "missing_strategy"})
            continue
        existing = {x.strip() for x in strat.get("structural_signals", [])}
        plan.append({"rule": r["id"], "signal": sig, "strategy": rs,
                     "status": "present" if sig in existing else "append"})
    return plan


def _appends_by_strategy(plan: list[dict]) -> dict[str, list[str]]:
    """strategy_id -> ordered, de-duplicated list of signals to append (status=='append')."""
    out: dict[str, list[str]] = {}
    for row in plan:
        if row["status"] != "append":
            continue
        lst = out.setdefault(row["strategy"], [])
        if row["signal"] not in lst:          # a strategy recommended by two rules with
            lst.append(row["signal"])          # the same signal appends it once
    return out


def _apply_surgery(text: str, appends: dict[str, list[str]], xlink: dict[str, str],
                   already_linked: set[str]) -> str:
    """Line-surgical fold + cross-link, preserving every untouched byte.

    Walks the file tracking the current strategy id. Rebuilds ONLY a folded strategy's
    ``structural_signals`` block (existing items verbatim, comma fixed on the last, new
    items appended); inserts one ``agent_pattern`` line after an agent strategy's
    ``category`` line when the strategy is not already linked. Idempotent by construction.
    """
    lines = text.split("\n")
    out: list[str] = []
    current_id: str | None = None
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        m_id = re.match(r'\s*"id":\s*"([^"]+)"', line)
        if m_id:
            current_id = m_id.group(1)
        # Fold: rebuild this strategy's structural_signals array.
        if (current_id in appends
                and re.match(r'\s*"structural_signals":\s*\[\s*$', line)):
            out.append(line)                         # opening "[" line
            j = i + 1
            item_lines: list[str] = []
            while not re.match(r'\s*\]', lines[j]):
                item_lines.append(lines[j])
                j += 1
            close_line = lines[j]                    # "      ]," or "      ]"
            if item_lines:
                item_lines[-1] = item_lines[-1].rstrip()
                if not item_lines[-1].endswith(","):
                    item_lines[-1] += ","
            new = ["        " + json.dumps(s, ensure_ascii=False) for s in appends[current_id]]
            for k in range(len(new)):
                if k < len(new) - 1:
                    new[k] += ","
            out.extend(item_lines)
            out.extend(new)
            out.append(close_line)
            i = j + 1
            continue
        out.append(line)
        # Cross-link: one reference line after the agent strategy's category line.
        if (current_id in xlink and current_id not in already_linked
                and re.match(r'\s*"category":\s*"agent",\s*$', line)):
            out.append(f'      "agent_pattern": "{xlink[current_id]}",')
        i += 1
    return "\n".join(out)


def _write_proofs(plan: list[dict], xlink: dict[str, str]) -> None:
    appended = [p for p in plan if p["status"] == "append"]
    present = [p for p in plan if p["status"] == "present"]
    lines = [
        "# Themis S2 migration proofs (story-6c63a3bd)",
        "",
        "Council 25d9a8ea / m-6ce2dcc3. `decision_rules` dissolved onto the strategy",
        "corpus (COPY, decision_rules kept until S5) + agent view cross-link.",
        "",
        f"## Fold: {len(plan)} rules -> {len(appended)} appended, {len(present)} already present",
        "",
        "| rule | recommended_strategy | status | signal |",
        "| --- | --- | --- | --- |",
    ]
    for p in plan:
        lines.append(f"| {p['rule']} | {p['strategy']} | {p['status']} | {p['signal']} |")
    lines += ["", f"## Cross-link: {len(xlink)} agent strategies -> twin agent_patterns id", "",
              "| agent strategy | agent_pattern |", "| --- | --- |"]
    for s, pat in xlink.items():
        lines.append(f"| {s} | {pat} |")
    lines.append("")
    PROOFS.parent.mkdir(parents=True, exist_ok=True)
    PROOFS.write_text("\n".join(lines), encoding="utf-8")


def migrate() -> dict:
    strategies_doc = json.loads(STRATEGIES.read_bytes().decode("utf-8"))
    strategies = strategies_doc["strategies"]
    rules = json.loads(RULES.read_bytes().decode("utf-8"))["rules"]
    pattern_ids = {p["id"] for p in json.loads(PATTERNS.read_bytes().decode("utf-8"))["patterns"]}

    # Validate the cross-link references only EXISTING pattern ids (fail closed).
    for s_id, p_id in AGENT_XLINK.items():
        if p_id not in pattern_ids:
            raise SystemExit(f"cross-link {s_id} -> {p_id!r}: not an agent_patterns id")

    plan = fold_plan(strategies, rules)
    missing = [p for p in plan if p["status"] == "missing_strategy"]
    if missing:
        raise SystemExit(f"fold: rules recommend unknown strategies: {missing}")

    appends = _appends_by_strategy(plan)
    already_linked = {s["id"] for s in strategies if "agent_pattern" in s}

    text = STRATEGIES.read_bytes().decode("utf-8")
    had_trailing = text.endswith("\r\n")
    text = text.replace("\r\n", "\n")
    new_text = _apply_surgery(text, appends, AGENT_XLINK, already_linked)

    # json.loads validates the surgery produced well-formed JSON before we write it.
    validated = json.loads(new_text)
    # Post-conditions: every fold landed; every cross-link present.
    by_id = {s["id"]: s for s in validated["strategies"]}
    for s_id, sigs in appends.items():
        have = {x.strip() for x in by_id[s_id]["structural_signals"]}
        assert set(sigs) <= have, f"fold incomplete for {s_id}"
    for s_id, p_id in AGENT_XLINK.items():
        assert by_id[s_id].get("agent_pattern") == p_id, f"cross-link missing for {s_id}"

    out_bytes = new_text.encode("utf-8").replace(b"\n", b"\r\n")
    if not had_trailing and out_bytes.endswith(b"\r\n"):
        out_bytes = out_bytes[:-2]
    STRATEGIES.write_bytes(out_bytes)

    # Write the provenance record only for a real fold event; a no-op idempotent re-run
    # (corpus already folded -> 0 appends) must not clobber the durable record with a
    # "0 appended, all present" restatement.
    appended = sum(1 for p in plan if p["status"] == "append")
    if appended or not PROOFS.exists():
        _write_proofs(plan, AGENT_XLINK)

    return {"plan": plan, "appended": appended,
            "present": sum(1 for p in plan if p["status"] == "present"),
            "appends_by_strategy": appends, "xlink": AGENT_XLINK}


if __name__ == "__main__":
    r = migrate()
    print(f"fold: {r['appended']} appended, {r['present']} already present "
          f"({len(r['appends_by_strategy'])} strategies gained signals)")
    print(f"cross-link: {len(r['xlink'])} agent strategies -> twin patterns")
    print(f"proofs -> {PROOFS}")
