# Copyright (c) 2026 Reza Malik. Licensed under the Apache License, Version 2.0.
"""MCP tool: run_agent_test

Execute test cases against an agent endpoint using the adapter registry.
Async — each test case is sent through the adapter, judged, and results
are aggregated into a summary.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

from themis.adapters.base import (
    AdapterConfig,
    AdapterError,
    AdapterTimeoutError,
    AgentAdapter,
    AgentResponse,
)
from themis.tools._shared import coerce, emit_event
from themis.tools.judge_output import judge_output

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Adapter registry — maps adapter_type strings to classes
# ---------------------------------------------------------------------------

_ADAPTER_REGISTRY: dict[str, type[AgentAdapter]] = {}


def register_adapter(name: str, cls: type[AgentAdapter]) -> None:
    """Register an adapter class under a string name."""
    _ADAPTER_REGISTRY[name.lower()] = cls


def _get_adapter_class(adapter_type: str) -> type[AgentAdapter]:
    """Resolve an adapter type string to a class.

    Tries the registry first, then attempts dynamic import from
    ``themis.adapters.<adapter_type>``.
    """
    key = adapter_type.lower()

    if key in _ADAPTER_REGISTRY:
        return _ADAPTER_REGISTRY[key]

    # Dynamic import — convention: themis.adapters.<name>.<Name>Adapter
    try:
        import importlib
        module = importlib.import_module(f"themis.adapters.{key}")
        # Find the first AgentAdapter subclass in the module
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (
                isinstance(attr, type)
                and issubclass(attr, AgentAdapter)
                and attr is not AgentAdapter
            ):
                _ADAPTER_REGISTRY[key] = attr
                return attr
    except (ImportError, AttributeError):
        pass

    raise ValueError(
        f"Unknown adapter type '{adapter_type}'. "
        f"Available: {list(_ADAPTER_REGISTRY.keys())}"
    )


# ---------------------------------------------------------------------------
# Single test execution
# ---------------------------------------------------------------------------

async def _run_single_test(
    adapter: AgentAdapter,
    test_case: dict[str, Any],
    default_timeout_ms: int,
    conn: object = None,
) -> dict[str, Any]:
    """Execute a single test case and return the result dict."""
    test_id = test_case.get("id", "unnamed")
    input_text = test_case.get("input", "")
    timeout_ms = test_case.get("timeout_ms", default_timeout_ms)
    criteria = test_case.get("criteria")

    start_ms = time.monotonic() * 1000.0

    try:
        # Send with timeout
        response: AgentResponse = await asyncio.wait_for(
            adapter.send(input_text),
            timeout=timeout_ms / 1000.0,
        )

        latency_ms = (time.monotonic() * 1000.0) - start_ms

        # Prepare test case with actual data for judging
        judge_case = dict(test_case)
        judge_case["actual_tool_calls"] = response.tool_calls
        judge_case["actual_tokens_used"] = response.tokens_used

        # Judge the output
        judgement = await asyncio.to_thread(
            judge_output,
            test_case=judge_case,
            actual_output=response.content,
            criteria=criteria,
            conn=conn,
        )

        return {
            "test_id": test_id,
            "verdict": judgement["verdict"],
            "score": judgement["score"],
            "latency_ms": round(latency_ms, 2),
            "tokens_used": response.tokens_used,
            "response": response.content,
            "deviations": judgement["deviations"],
            "checks_performed": judgement.get("checks_performed", []),
            "tool_call_analysis": judgement.get("tool_call_analysis"),
            "token_usage_analysis": judgement.get("token_usage_analysis"),
            "error": None,
        }

    except asyncio.TimeoutError:
        latency_ms = (time.monotonic() * 1000.0) - start_ms
        return {
            "test_id": test_id,
            "verdict": "fail",
            "score": 0.0,
            "latency_ms": round(latency_ms, 2),
            "tokens_used": 0,
            "response": "",
            "deviations": [f"Timeout after {timeout_ms}ms"],
            "checks_performed": [],
            "tool_call_analysis": None,
            "token_usage_analysis": None,
            "error": f"TimeoutError: exceeded {timeout_ms}ms",
        }

    except AdapterTimeoutError as exc:
        latency_ms = (time.monotonic() * 1000.0) - start_ms
        return {
            "test_id": test_id,
            "verdict": "fail",
            "score": 0.0,
            "latency_ms": round(latency_ms, 2),
            "tokens_used": 0,
            "response": "",
            "deviations": [f"Adapter timeout: {exc}"],
            "checks_performed": [],
            "tool_call_analysis": None,
            "token_usage_analysis": None,
            "error": f"AdapterTimeoutError: {exc}",
        }

    except AdapterError as exc:
        latency_ms = (time.monotonic() * 1000.0) - start_ms
        logger.warning("Adapter error on test %s: %s", test_id, exc)
        return {
            "test_id": test_id,
            "verdict": "fail",
            "score": 0.0,
            "latency_ms": round(latency_ms, 2),
            "tokens_used": 0,
            "response": "",
            "deviations": [f"Adapter error: {exc}"],
            "checks_performed": [],
            "tool_call_analysis": None,
            "token_usage_analysis": None,
            "error": f"AdapterError: {exc}",
        }

    except Exception as exc:
        latency_ms = (time.monotonic() * 1000.0) - start_ms
        logger.exception("Unexpected error on test %s", test_id)
        return {
            "test_id": test_id,
            "verdict": "fail",
            "score": 0.0,
            "latency_ms": round(latency_ms, 2),
            "tokens_used": 0,
            "response": "",
            "deviations": [f"Unexpected error: {type(exc).__name__}: {exc}"],
            "checks_performed": [],
            "tool_call_analysis": None,
            "token_usage_analysis": None,
            "error": f"{type(exc).__name__}: {exc}",
        }


# ---------------------------------------------------------------------------
# Main tool
# ---------------------------------------------------------------------------

async def run_agent_test(
    agent_endpoint: str,
    adapter_type: str,
    test_cases: list[dict],
    config: dict | None = None,
    conn: object = None,
) -> dict:
    """Execute test cases against an agent endpoint.

    Args:
        agent_endpoint: URL, path, or identifier for the agent under test.
        adapter_type: Adapter to use — e.g. "http", "websocket", "mcp",
            "subprocess".  Must be registered or discoverable.
        test_cases: List of test case dicts, each with:
            - ``id`` (str): Unique test identifier.
            - ``input`` (str): The prompt to send.
            - ``expected_output`` (str): Expected response.
            - ``criteria`` (dict): Judgement criteria (see judge_output).
            - ``timeout_ms`` (int): Per-test timeout override.
        config: Optional adapter configuration overrides:
            - ``timeout_ms`` (int): Default timeout per test.
            - ``max_retries`` (int): Retry count on transient failures.
            - ``headers`` (dict): HTTP headers to include.
            - ``auth`` (str): Authentication token.
            - ``concurrency`` (int): Max concurrent tests (default 1).
        conn: Kuzu/LadybugDB connection for graph mode, or None.

    Returns:
        Dict with keys: results, summary, timestamp.
    """
    test_cases = coerce(test_cases, list) or []
    config = coerce(config, dict) or {}

    if not test_cases:
        return {
            "results": [],
            "summary": {
                "total": 0, "passed": 0, "failed": 0, "warnings": 0,
                "avg_latency_ms": 0.0, "total_tokens": 0,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": "No test cases provided",
        }

    # Build adapter config
    adapter_config = AdapterConfig(
        endpoint=agent_endpoint,
        timeout_ms=config.get("timeout_ms", 30_000),
        max_retries=config.get("max_retries", 0),
        headers=config.get("headers", {}),
        auth=config.get("auth"),
    )

    concurrency = config.get("concurrency", 1)
    default_timeout_ms = adapter_config.timeout_ms

    # Resolve adapter class
    try:
        adapter_cls = _get_adapter_class(adapter_type)
    except ValueError as exc:
        return {
            "results": [],
            "summary": {
                "total": len(test_cases), "passed": 0,
                "failed": len(test_cases), "warnings": 0,
                "avg_latency_ms": 0.0, "total_tokens": 0,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error": str(exc),
        }

    # Execute tests
    results: list[dict[str, Any]] = []

    if concurrency <= 1:
        # Sequential execution
        adapter = adapter_cls(adapter_config)
        try:
            async with adapter:
                for tc in test_cases:
                    result = await _run_single_test(
                        adapter, tc, default_timeout_ms, conn,
                    )
                    results.append(result)
        except Exception as exc:
            # Connection-level failure — all remaining tests fail
            logger.error("Adapter connection failed: %s", exc)
            for tc in test_cases[len(results):]:
                results.append({
                    "test_id": tc.get("id", "unnamed"),
                    "verdict": "fail",
                    "score": 0.0,
                    "latency_ms": 0.0,
                    "tokens_used": 0,
                    "response": "",
                    "deviations": [f"Connection failure: {exc}"],
                    "checks_performed": [],
                    "tool_call_analysis": None,
                    "token_usage_analysis": None,
                    "error": f"ConnectionError: {exc}",
                })
    else:
        # Concurrent execution with semaphore
        sem = asyncio.Semaphore(concurrency)

        async def _guarded(tc: dict) -> dict:
            async with sem:
                adapter = adapter_cls(adapter_config)
                async with adapter:
                    return await _run_single_test(
                        adapter, tc, default_timeout_ms, conn,
                    )

        results = await asyncio.gather(
            *[_guarded(tc) for tc in test_cases],
            return_exceptions=False,
        )
        results = list(results)

    # Compute summary
    passed = sum(1 for r in results if r["verdict"] == "pass")
    failed = sum(1 for r in results if r["verdict"] == "fail")
    warnings = sum(1 for r in results if r["verdict"] == "warning")
    total_latency = sum(r.get("latency_ms", 0) for r in results)
    total_tokens = sum(r.get("tokens_used", 0) for r in results)

    summary = {
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "warnings": warnings,
        "pass_rate": round(passed / len(results), 4) if results else 0.0,
        "avg_latency_ms": round(total_latency / len(results), 2) if results else 0.0,
        "total_tokens": total_tokens,
    }

    timestamp = datetime.now(timezone.utc).isoformat()

    emit_event("run_agent_test", {
        "agent_endpoint": agent_endpoint,
        "adapter_type": adapter_type,
        "total": len(results),
        "passed": passed,
        "failed": failed,
        "warnings": warnings,
        "avg_latency_ms": summary["avg_latency_ms"],
    })

    return {
        "results": results,
        "summary": summary,
        "timestamp": timestamp,
    }
