# Copyright (c) 2026 Reza Malik. Licensed under the Apache License, Version 2.0.
"""MCP tool: log_verdict

Record test verdicts and analysis results to persistent storage.
Dual-mode: conn=None writes to local JSONL, conn provided writes to
Kuzu graph memories table (memory_type="test_verdict").
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from themis.tools._shared import append_verdict, coerce_or_raise, emit_event

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Valid modes and verdicts
# ---------------------------------------------------------------------------

_VALID_MODES = {"agent_test", "strategy_review", "coverage_analysis", "code_review", "audit"}
_VALID_VERDICTS = {"pass", "fail", "warning"}


# ---------------------------------------------------------------------------
# Graph-mode storage
# ---------------------------------------------------------------------------

def _write_to_graph(
    conn: Any,
    mode: str,
    system_tested: str,
    verdict: str,
    details: dict[str, Any],
    timestamp: str,
) -> str:
    """Write a verdict record to the Kuzu graph memories table.

    Uses the same schema convention as Mnemos: a 'memories' node table with
    memory_type, content (JSON), and timestamp fields.

    Returns the verdict_id.
    """
    import hashlib
    import json

    record = {
        "memory_type": "test_verdict",
        "mode": mode,
        "system_tested": system_tested,
        "verdict": verdict,
        "details": details,
        "timestamp": timestamp,
    }

    raw = json.dumps(record, sort_keys=True)
    verdict_id = "v-" + hashlib.sha256(raw.encode()).hexdigest()[:12]

    content_json = "JSON:" + json.dumps(record)

    conn.execute(
        "CREATE (m:memories {"
        "  id: $id,"
        "  content: $content,"
        "  memory_type: $type,"
        "  status: $status,"
        "  outcome: $outcome,"
        "  agent: $agent,"
        "  project: $project,"
        "  confidence: $confidence,"
        "  timestamp: $ts"
        "})",
        parameters={
            "id": verdict_id,
            "content": content_json,
            "type": "test_verdict",
            "status": "active",
            "outcome": verdict,
            "agent": "themis",
            "project": f"themis:{mode}",
            "confidence": 1.0,
            "ts": timestamp,
        },
    )

    return verdict_id


# ---------------------------------------------------------------------------
# Main tool
# ---------------------------------------------------------------------------

def log_verdict(
    mode: str,
    system_tested: str,
    verdict: str,
    details: dict | None = None,
    conn: object = None,
) -> dict:
    """Record a test verdict to persistent storage.

    Args:
        mode: Context of the verdict — one of ``"agent_test"``,
            ``"strategy_review"``, ``"coverage_analysis"``,
            ``"code_review"``, ``"audit"``.
        system_tested: Identifier for the system/agent that was tested.
        verdict: Overall verdict — one of ``"pass"``, ``"fail"``,
            ``"warning"``.
        details: Optional dict with additional context.  Typical keys:
            - ``test_count`` (int): Number of tests run.
            - ``pass_count`` (int): Number passed.
            - ``fail_count`` (int): Number failed.
            - ``scores`` (list[float]): Individual test scores.
            - ``deviations`` (list[str]): Notable deviations found.
            - ``coverage_pct`` (float): Coverage percentage.
            - ``risk_areas`` (list[str]): Identified risk areas.
            - ``recommendations`` (list[str]): Suggested improvements.
        conn: Kuzu/LadybugDB connection for graph mode, or None for JSON.

    Returns:
        Dict with keys: logged, verdict_id, mode, system_tested, verdict,
        timestamp, storage_mode.
    """
    details = coerce_or_raise(details, dict, {})

    # Validate mode
    effective_mode = mode.lower().strip()
    if effective_mode not in _VALID_MODES:
        logger.warning(
            "Unknown mode '%s', accepting anyway (valid: %s)",
            mode, _VALID_MODES,
        )
        effective_mode = mode  # accept non-standard modes gracefully

    # Validate verdict
    effective_verdict = verdict.lower().strip()
    if effective_verdict not in _VALID_VERDICTS:
        logger.warning(
            "Unknown verdict '%s', accepting anyway (valid: %s)",
            verdict, _VALID_VERDICTS,
        )
        effective_verdict = verdict

    timestamp = datetime.now(timezone.utc).isoformat()

    # Enrich details with computed fields
    enriched_details = dict(details)
    if "scores" in enriched_details:
        scores = enriched_details["scores"]
        if isinstance(scores, list) and scores:
            enriched_details["avg_score"] = round(
                sum(scores) / len(scores), 4,
            )
            enriched_details["min_score"] = round(min(scores), 4)
            enriched_details["max_score"] = round(max(scores), 4)

    if conn is not None:
        # Graph mode — write to Kuzu
        storage_mode = "graph"
        verdict_id = _write_to_graph(
            conn, effective_mode, system_tested,
            effective_verdict, enriched_details, timestamp,
        )
    else:
        # Standalone mode — write to local JSONL
        storage_mode = "json"
        record = {
            "mode": effective_mode,
            "system_tested": system_tested,
            "verdict": effective_verdict,
            "details": enriched_details,
        }
        verdict_id = append_verdict(record)

    result: dict[str, Any] = {
        "logged": True,
        "verdict_id": verdict_id,
        "mode": effective_mode,
        "system_tested": system_tested,
        "verdict": effective_verdict,
        "timestamp": timestamp,
        "storage_mode": storage_mode,
    }

    emit_event("verdict_logged", {
        "verdict_id": verdict_id,
        "mode": effective_mode,
        "system_tested": system_tested,
        "verdict": effective_verdict,
        "storage_mode": storage_mode,
    })

    return result
