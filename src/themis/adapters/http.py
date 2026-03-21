# Copyright (c) 2026 Reza Malik. Licensed under the Apache License, Version 2.0.
"""HTTP adapter — connects to REST API agents."""
from __future__ import annotations

import json
import logging
from typing import Any

try:
    import httpx
except ImportError as _exc:
    raise ImportError(
        "The httpx package is required for HTTPAdapter. "
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

# Common response-header names that carry token counts.
_TOKEN_HEADERS = (
    "x-token-count",
    "x-tokens-used",
    "x-total-tokens",
    "x-usage-total-tokens",
)


class HTTPAdapter(AgentAdapter):
    """Adapter for agents exposed as REST (HTTP/HTTPS) endpoints.

    Supports two modes:

    * **single-response** — POST a JSON body and read the full response.
    * **streaming (SSE)** — POST and consume a ``text/event-stream``
      response, collecting chunks along the way.

    The mode is auto-detected from the response ``Content-Type``, or you
    can force streaming by setting ``metadata["stream"] = True`` in the
    send context.
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
        headers = {**self.config.headers}
        if self.config.auth:
            headers["Authorization"] = self.config.auth

        self._client = httpx.AsyncClient(
            headers=headers,
            timeout=httpx.Timeout(self.config.timeout_seconds),
            follow_redirects=True,
        )
        self._connected = True
        logger.info("HTTP adapter ready for %s", self.config.endpoint)

    async def disconnect(self) -> None:
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass
            finally:
                self._client = None
                self._connected = False
                logger.info("HTTP adapter closed")

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

        force_stream = (context or {}).get("stream", False)
        start = self._now_ms()

        try:
            if force_stream:
                return await self._stream_request(body, start)
            resp = await self._client.post(
                self.config.endpoint,
                json=body,
            )
            resp.raise_for_status()
        except httpx.TimeoutException as exc:
            raise AdapterTimeoutError(
                f"HTTP request timed out after {self.config.timeout_ms}ms"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise AdapterError(
                f"HTTP {exc.response.status_code}: {exc.response.text[:500]}"
            ) from exc
        except Exception as exc:
            raise AdapterError(f"HTTP request failed: {exc}") from exc

        latency = self._elapsed_ms(start)

        # Auto-detect SSE even when not forced.
        ct = resp.headers.get("content-type", "")
        if "text/event-stream" in ct:
            # Shouldn't normally reach here (httpx buffers), but handle it.
            return self._parse_sse_body(resp.text, latency, resp)

        return self._parse_response(resp, latency)

    # ------------------------------------------------------------------
    # Single-response parsing
    # ------------------------------------------------------------------

    def _parse_response(self, resp: httpx.Response, latency: float) -> AgentResponse:
        tokens = self._extract_token_count(resp)
        ct = resp.headers.get("content-type", "")

        if "application/json" in ct:
            try:
                data = resp.json()
            except Exception:
                data = {}
            content = data.get("content", "") or data.get("response", "") or data.get("text", "")
            if not content and isinstance(data, str):
                content = data
            tool_calls = data.get("tool_calls", []) if isinstance(data, dict) else []
            if isinstance(data, dict) and not tokens:
                usage = data.get("usage", {})
                tokens = usage.get("total_tokens", 0) if isinstance(usage, dict) else 0
        else:
            content = resp.text
            tool_calls = []
            data = None

        return AgentResponse(
            content=str(content),
            tool_calls=tool_calls,
            tokens_used=tokens,
            latency_ms=latency,
            metadata={"status_code": resp.status_code},
            raw=resp,
        )

    # ------------------------------------------------------------------
    # Streaming (SSE)
    # ------------------------------------------------------------------

    async def _stream_request(
        self,
        body: dict[str, Any],
        start: float,
    ) -> AgentResponse:
        assert self._client is not None

        chunks: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        ttft: float | None = None
        tokens = 0

        try:
            async with self._client.stream(
                "POST",
                self.config.endpoint,
                json=body,
            ) as resp:
                resp.raise_for_status()
                tokens = self._extract_token_count(resp)

                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data_str = line[len("data:"):].strip()
                    if data_str == "[DONE]":
                        break

                    if ttft is None:
                        ttft = self._elapsed_ms(start)

                    try:
                        event = json.loads(data_str)
                    except json.JSONDecodeError:
                        chunks.append(data_str)
                        continue

                    # Handle different SSE event shapes.
                    if isinstance(event, dict):
                        delta = event.get("delta", {})
                        chunk_text = (
                            delta.get("content", "")
                            or event.get("content", "")
                            or event.get("text", "")
                        )
                        if chunk_text:
                            chunks.append(chunk_text)

                        if "tool_calls" in event:
                            tool_calls.extend(event["tool_calls"])

                        usage = event.get("usage", {})
                        if isinstance(usage, dict) and usage.get("total_tokens"):
                            tokens = usage["total_tokens"]
                    else:
                        chunks.append(str(event))

        except httpx.TimeoutException as exc:
            raise AdapterTimeoutError(
                f"HTTP stream timed out after {self.config.timeout_ms}ms"
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise AdapterError(
                f"HTTP stream {exc.response.status_code}: {exc.response.text[:500]}"
            ) from exc
        except Exception as exc:
            raise AdapterError(f"HTTP stream failed: {exc}") from exc

        latency = self._elapsed_ms(start)
        content = "".join(chunks)

        return AgentResponse(
            content=content,
            tool_calls=tool_calls,
            tokens_used=tokens,
            latency_ms=latency,
            chunks=chunks,
            metadata={
                "time_to_first_token_ms": ttft,
                "streaming": True,
            },
            raw=None,
        )

    # ------------------------------------------------------------------
    # SSE body fallback (if the full body was already buffered)
    # ------------------------------------------------------------------

    def _parse_sse_body(
        self, text: str, latency: float, resp: httpx.Response
    ) -> AgentResponse:
        chunks: list[str] = []
        for line in text.splitlines():
            if line.startswith("data:"):
                data_str = line[len("data:"):].strip()
                if data_str and data_str != "[DONE]":
                    try:
                        event = json.loads(data_str)
                        chunk = event.get("content", "") or event.get("text", data_str)
                    except json.JSONDecodeError:
                        chunk = data_str
                    chunks.append(chunk)

        return AgentResponse(
            content="".join(chunks),
            tokens_used=self._extract_token_count(resp),
            latency_ms=latency,
            chunks=chunks,
            metadata={"status_code": resp.status_code, "streaming": True},
            raw=resp,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_token_count(resp: httpx.Response) -> int:
        for hdr in _TOKEN_HEADERS:
            val = resp.headers.get(hdr)
            if val is not None:
                try:
                    return int(val)
                except ValueError:
                    continue
        return 0
