# Copyright (c) 2026 Reza Malik. Licensed under the Apache License, Version 2.0.
"""Shared state and utilities for all Themis tools.

Every tool module imports from here to get access to the singleton
KnowledgeLoader and dual-mode support (standalone JSON vs Othrys graph).
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from themis.knowledge.loader import KnowledgeLoader

# ---------------------------------------------------------------------------
# Singletons — shared across all tool modules
# ---------------------------------------------------------------------------

_knowledge: KnowledgeLoader | None = None


def get_knowledge(conn: Any = None) -> KnowledgeLoader:
    """Return the appropriate knowledge loader for the current mode.

    Args:
        conn: If provided, returns a GraphKnowledgeLoader backed by this
              Kuzu/LadybugDB connection.  If None, returns the JSON singleton.
    """
    if conn is not None:
        from themis.knowledge.graph_loader import GraphKnowledgeLoader
        return GraphKnowledgeLoader(conn)
    global _knowledge
    if _knowledge is None:
        _knowledge = KnowledgeLoader()
    return _knowledge


# ---------------------------------------------------------------------------
# Verdict log — local JSON file for standalone mode
# ---------------------------------------------------------------------------

def _verdicts_dir() -> Path:
    """Return the path to the verdicts storage directory."""
    env = os.environ.get("THEMIS_DATA_DIR")
    base = Path(env) if env else Path.home() / ".themis" / "data"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _verdicts_file() -> Path:
    """Return the path to the local verdicts JSONL file."""
    return _verdicts_dir() / "verdicts.jsonl"


def append_verdict(record: dict[str, Any]) -> str:
    """Append a verdict record to the local JSONL log.

    Returns the verdict_id.
    """
    import hashlib

    ts = datetime.now(timezone.utc).isoformat()
    record["timestamp"] = ts
    raw = json.dumps(record, sort_keys=True)
    verdict_id = "v-" + hashlib.sha256(raw.encode()).hexdigest()[:12]
    record["verdict_id"] = verdict_id

    vf = _verdicts_file()
    vf.parent.mkdir(parents=True, exist_ok=True)
    with open(vf, "a", encoding="utf-8") as f:
        f.write(json.dumps(record) + "\n")

    return verdict_id


# ---------------------------------------------------------------------------
# Event system — file-based for cross-process dashboard communication
# ---------------------------------------------------------------------------

_event_listeners: list[Callable[[str, dict], None]] = []


def _events_file() -> Path:
    """Return the path to the shared events JSONL file."""
    return _verdicts_dir() / "events.jsonl"


def on_event(callback: Callable[[str, dict], None]) -> None:
    """Register a callback that receives (event_name, payload) on every emit."""
    _event_listeners.append(callback)


def emit_event(event_name: str, payload: dict[str, Any]) -> None:
    """Fire an event to all registered listeners and append to events file.

    The events file (events.jsonl) is the cross-process bridge between the
    MCP server (which emits events) and the dashboard (which reads them).
    """
    for cb in _event_listeners:
        try:
            cb(event_name, payload)
        except Exception:
            pass

    try:
        event = {
            "type": event_name,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **payload,
        }
        ef = _events_file()
        ef.parent.mkdir(parents=True, exist_ok=True)
        with open(ef, "a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")
    except Exception:
        pass  # best-effort — never break tool execution


# ---------------------------------------------------------------------------
# Coercion utility — MCP clients sometimes send JSON as strings
# ---------------------------------------------------------------------------

def coerce(val: Any, expected_type: type) -> Any:
    """Coerce JSON-encoded strings to native types (MCP client compat)."""
    if val is None:
        return None
    if isinstance(val, str) and expected_type in (list, dict):
        try:
            parsed = json.loads(val)
            if isinstance(parsed, expected_type):
                return parsed
        except (ValueError, TypeError):
            pass
    return val
