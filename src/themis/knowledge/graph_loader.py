# Copyright (c) 2026 Reza Malik. Licensed under the Apache License, Version 2.0.
"""Graph-backed knowledge loader for Themis.

Wraps the JSON-based KnowledgeLoader (data stays in JSON for speed) and adds
write_memory() for persisting test verdicts to the Kuzu graph.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from themis.knowledge.loader import KnowledgeLoader


class GraphKnowledgeLoader(KnowledgeLoader):
    """KnowledgeLoader backed by a Kuzu/LadybugDB connection.

    Read path: delegates to the parent JSON-based KnowledgeLoader (the
    knowledge JSON files are the source of truth for test strategies,
    agent patterns, decision rules, and frameworks).

    Write path: ``write_memory()`` persists records as Memory nodes in the
    Kuzu graph so they can be queried by Othrys and other Titans.
    """

    def __init__(self, conn: Any) -> None:
        super().__init__()
        self._conn = conn
        self._ensure_schema()

    # ------------------------------------------------------------------
    # Schema bootstrap
    # ------------------------------------------------------------------

    def _ensure_schema(self) -> None:
        """Create the Memory node table if it does not already exist."""
        try:
            self._conn.execute(
                "CREATE NODE TABLE IF NOT EXISTS Memory("
                "id STRING, "
                "memory_type STRING, "
                "data STRING, "
                "created_at STRING, "
                "PRIMARY KEY (id))"
            )
        except Exception:
            pass  # table may already exist or conn may not support DDL

    # ------------------------------------------------------------------
    # Write path
    # ------------------------------------------------------------------

    def write_memory(
        self,
        memory_type: str,
        data: dict[str, Any],
    ) -> str:
        """Write a memory record to the Kuzu graph.

        Args:
            memory_type: Category of memory, e.g. "test_verdict".
            data: Arbitrary dict payload to persist.

        Returns:
            The generated memory ID (``m-<hash>``).
        """
        ts = datetime.now(timezone.utc).isoformat()
        data_with_ts = {**data, "timestamp": ts}
        raw = json.dumps(data_with_ts, sort_keys=True)
        memory_id = "m-" + hashlib.sha256(raw.encode()).hexdigest()[:12]

        data_str = "JSON:" + json.dumps(data_with_ts)

        try:
            self._conn.execute(
                "CREATE (m:Memory {"
                "id: $id, "
                "memory_type: $memory_type, "
                "data: $data, "
                "created_at: $created_at})",
                parameters={
                    "id": memory_id,
                    "memory_type": memory_type,
                    "data": data_str,
                    "created_at": ts,
                },
            )
        except Exception:
            escaped_data = data_str.replace("'", "\\'")
            self._conn.execute(
                f"CREATE (m:Memory {{"
                f"id: '{memory_id}', "
                f"memory_type: '{memory_type}', "
                f"data: '{escaped_data}', "
                f"created_at: '{ts}'}})"
            )

        return memory_id
