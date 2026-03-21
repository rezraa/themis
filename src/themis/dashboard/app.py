# Copyright (c) 2026 Reza Malik. Licensed under the Apache License, Version 2.0.
"""Themis Dashboard -- Real-time test execution and verdict visualization.

A live dashboard showing test results as they happen. Color-coded verdicts,
response diffs, timing charts, and test history.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import deque
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).parent


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------

class Verdict(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARN = "WARN"


@dataclass
class TestResult:
    id: str
    name: str
    verdict: str
    latency_ms: float
    tokens_used: int
    score: float  # 0.0 - 1.0
    expected: str
    actual: str
    timestamp: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# In-memory store (last 1000 results)
# ---------------------------------------------------------------------------

MAX_HISTORY = 1000

_results: deque[TestResult] = deque(maxlen=MAX_HISTORY)
_connected_ws: set[WebSocket] = set()


def _aggregate_stats() -> dict:
    total = len(_results)
    if total == 0:
        return {
            "total": 0,
            "pass": 0,
            "fail": 0,
            "warn": 0,
            "pass_rate": 0.0,
            "avg_latency_ms": 0.0,
            "avg_score": 0.0,
        }
    passes = sum(1 for r in _results if r.verdict == Verdict.PASS)
    fails = sum(1 for r in _results if r.verdict == Verdict.FAIL)
    warns = sum(1 for r in _results if r.verdict == Verdict.WARN)
    avg_lat = sum(r.latency_ms for r in _results) / total
    avg_score = sum(r.score for r in _results) / total
    return {
        "total": total,
        "pass": passes,
        "fail": fails,
        "warn": warns,
        "pass_rate": round(passes / total * 100, 2),
        "avg_latency_ms": round(avg_lat, 2),
        "avg_score": round(avg_score * 100, 2),
    }


# ---------------------------------------------------------------------------
# Broadcast helper
# ---------------------------------------------------------------------------

async def _broadcast(payload: dict) -> None:
    dead: list[WebSocket] = []
    for ws in _connected_ws:
        try:
            await ws.send_json(payload)
        except Exception:
            dead.append(ws)
    for ws in dead:
        _connected_ws.discard(ws)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------

app = FastAPI(title="Themis Dashboard", version="0.1.0")

app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")


@app.get("/", response_class=HTMLResponse)
async def index():
    html_path = ROOT / "templates" / "index.html"
    return HTMLResponse(content=html_path.read_text())


# -- WebSocket --------------------------------------------------------------

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    _connected_ws.add(ws)
    # Send current stats on connect
    await ws.send_json({"type": "stats", "data": _aggregate_stats()})
    # Send recent history
    for r in list(_results)[-50:]:
        await ws.send_json({"type": "result", "data": r.to_dict()})
    try:
        while True:
            # Keep alive -- clients can send pings or commands
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_json({"type": "pong"})
    except WebSocketDisconnect:
        _connected_ws.discard(ws)


# -- REST endpoints ---------------------------------------------------------

@app.get("/api/history")
async def get_history(limit: int = 100, verdict: str | None = None):
    results = list(_results)
    if verdict:
        results = [r for r in results if r.verdict == verdict.upper()]
    results = results[-limit:]
    return JSONResponse([r.to_dict() for r in results])


@app.get("/api/stats")
async def get_stats():
    return JSONResponse(_aggregate_stats())


@app.post("/api/run")
async def trigger_run(suite: dict | None = None):
    """Trigger a test suite. Accepts optional suite config in body.

    For demo purposes, generates synthetic results if no real test
    runner is wired up yet.
    """
    suite_name = (suite or {}).get("name", "default")
    run_id = str(uuid.uuid4())[:8]
    return JSONResponse({"status": "queued", "run_id": run_id, "suite": suite_name})


# -- Programmatic API for pushing results from test runners -----------------

async def push_result(result: TestResult) -> None:
    """Push a test result into the store and broadcast to all clients."""
    _results.append(result)
    await _broadcast({"type": "result", "data": result.to_dict()})
    await _broadcast({"type": "stats", "data": _aggregate_stats()})


@app.post("/api/results")
async def post_result(body: dict):
    """Accept a test result via REST and broadcast it."""
    result = TestResult(
        id=body.get("id", str(uuid.uuid4())[:8]),
        name=body["name"],
        verdict=body["verdict"],
        latency_ms=body.get("latency_ms", 0),
        tokens_used=body.get("tokens_used", 0),
        score=body.get("score", 0.0),
        expected=body.get("expected", ""),
        actual=body.get("actual", ""),
        timestamp=body.get("timestamp", time.time()),
        metadata=body.get("metadata", {}),
    )
    await push_result(result)
    return JSONResponse({"status": "ok", "id": result.id})


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8710)
