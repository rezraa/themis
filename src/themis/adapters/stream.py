# Copyright (c) 2026 Reza Malik. Licensed under the Apache License, Version 2.0.
"""Stream adapter — connects to Server-Sent Events (SSE) endpoints."""
from __future__ import annotations

import json
import logging
from typing import Any

try:
    import httpx
except ImportError as _exc:
    raise ImportError(
        "The httpx package is required for StreamAdapter. "
        "Install it with: pip install httpx"
    ) from _exc

from .base import (
    AdapterConfig,
    AdapterError,
    AdapterTimeoutError,
    AgentAdapter,
    AgentResponse,
)

logger = logging.getLogger(__name__)


class StreamAdapter(AgentAdapter):
    """Adapter for agents that return Server-Sent Events (SSE).

    Unlike :class:`HTTPAdapter` with ``stream=True``, this adapter is
    purpose-built for SSE and adds:

    * **Chunk ordering validation** — detects out-of-order or missing chunks
      when the server provides an ``index`` field.
    * **Completeness checks** — verifies we received a ``[DONE]`` sentinel
      before the stream ended.
    * **Time-to-first-token** and **inter-chunk latency** metrics.
    * **Reconnection** on transient stream drops (up to ``max_retries``).
    """

    def __init__(self, config: AdapterConfig) -> None:
        super().__init__(config)
        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        if self._connected:
            return
        headers = {
            "Accept": "text/event-stream",
            **self.config.headers,
        }
        if self.config.auth:
            headers["Authorization"] = self.config.auth

        self._client = httpx.AsyncClient(
            headers=headers,
            timeout=httpx.Timeout(self.config.timeout_seconds),
            follow_redirects=True,
        )
        self._connected = True
        logger.info("Stream adapter ready for %s", self.config.endpoint)

    async def disconnect(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass
            finally:
                self._client = None
                self._connected = False
                logger.info("Stream adapter closed")

    # ------------------------------------------------------------------
    # Send
    # ------------------------------------------------------------------

    async def send(
        self,
        message: str,
        context: dict[str, Any] | None = None,
    ) -> AgentResponse:
        return await self._send_with_retries(message, context, self._do_send)

    async def _do_send(
        self,
        message: str,
        context: dict[str, Any] | None,
    ) -> AgentResponse:
        if not self._connected or self._client is None:
            await self.connect()
        assert self._client is not None

        body: dict[str, Any] = {"prompt": message}
        if context:
            body["context"] = context

        start = self._now_ms()
        chunks: list[str] = []
        chunk_times: list[float] = []
        tool_calls: list[dict[str, Any]] = []
        tokens = 0
        ttft: float | None = None
        done_received = False
        expected_index = 0
        ordering_errors: list[str] = []

        try:
            async with self._client.stream(
                "POST",
                self.config.endpoint,
                json=body,
            ) as resp:
                resp.raise_for_status()

                # Try to get token count from headers.
                for hdr in ("x-token-count", "x-tokens-used", "x-total-tokens"):
                    val = resp.headers.get(hdr)
                    if val:
                        try:
                            tokens = int(val)
                            break
                        except ValueError:
                            continue

                event_type: str | None = None

                async for line in resp.aiter_lines():
                    # SSE format: optional "event:" then "data:" lines,
                    # separated by blank lines.
                    if not line:
                        event_type = None
                        continue

                    if line.startswith("event:"):
                        event_type = line[len("event:"):].strip()
                        continue

                    if not line.startswith("data:"):
                        continue

                    data_str = line[len("data:"):].strip()

                    if data_str == "[DONE]":
                        done_received = True
                        break

                    now = self._now_ms()
                    if ttft is None:
                        ttft = now - start

                    chunk_times.append(now - start)

                    # Parse JSON event.
                    try:
                        event = json.loads(data_str)
                    except json.JSONDecodeError:
                        chunks.append(data_str)
                        expected_index += 1
                        continue

                    if not isinstance(event, dict):
                        chunks.append(str(event))
                        expected_index += 1
                        continue

                    # ---- Chunk ordering validation ----
                    idx = event.get("index")
                    if idx is not None:
                        try:
                            idx_int = int(idx)
                            if idx_int != expected_index:
                                ordering_errors.append(
                                    f"expected index {expected_index}, got {idx_int}"
                                )
                        except (ValueError, TypeError):
                            pass

                    expected_index += 1

                    # ---- Extract text ----
                    delta = event.get("delta", {})
                    chunk_text = (
                        delta.get("content", "")
                        or event.get("content", "")
                        or event.get("text", "")
                    )
                    if chunk_text:
                        chunks.append(chunk_text)

                    # ---- Tool calls ----
                    if "tool_calls" in event:
                        tool_calls.extend(event["tool_calls"])
                    elif event_type == "tool_call":
                        tool_calls.append({
                            "name": event.get("name", "unknown"),
                            "args": event.get("arguments", {}),
                            "result": event.get("result"),
                        })

                    # ---- Token usage (sometimes in final event) ----
                    usage = event.get("usage", {})
                    if isinstance(usage, dict) and usage.get("total_tokens"):
                        tokens = usage["total_tokens"]

        except httpx.TimeoutException as exc:
            raise AdapterTimeoutError(
                f"SSE stream timed out after {self.config.timeout_ms}ms"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise AdapterError(
                f"SSE stream HTTP {exc.response.status_code}: "
                f"{exc.response.text[:500]}"
            ) from exc
        except AdapterTimeoutError:
            raise
        except Exception as exc:
            raise AdapterError(f"SSE stream failed: {exc}") from exc

        latency = self._elapsed_ms(start)
        content = "".join(chunks)

        # Compute inter-chunk latencies.
        inter_chunk: list[float] = []
        for i in range(1, len(chunk_times)):
            inter_chunk.append(chunk_times[i] - chunk_times[i - 1])

        metadata: dict[str, Any] = {
            "streaming": True,
            "time_to_first_token_ms": ttft,
            "total_chunks": len(chunks),
            "done_received": done_received,
            "inter_chunk_latency_ms": inter_chunk,
        }
        if ordering_errors:
            metadata["ordering_errors"] = ordering_errors
            logger.warning(
                "Chunk ordering issues detected: %s", ordering_errors
            )
        if not done_received and chunks:
            logger.warning(
                "SSE stream ended without [DONE] sentinel — "
                "response may be incomplete (%d chunks received)",
                len(chunks),
            )
            metadata["possibly_incomplete"] = True

        return AgentResponse(
            content=content,
            tool_calls=tool_calls,
            tokens_used=tokens,
            latency_ms=latency,
            chunks=chunks,
            metadata=metadata,
            raw=None,
        )
