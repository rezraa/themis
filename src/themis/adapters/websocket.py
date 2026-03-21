# Copyright (c) 2026 Reza Malik. Licensed under the Apache License, Version 2.0.
"""WebSocket adapter — connects to MCP servers or WebSocket-based agents."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

try:
    import websockets
    from websockets.asyncio.client import ClientConnection, connect as ws_connect
except ImportError as _exc:
    raise ImportError(
        "The websockets package is required for WebSocketAdapter. "
        "Install it with: pip install websockets"
    ) from _exc

from .base import (
    AdapterConfig,
    AdapterError,
    AdapterTimeoutError,
    AgentAdapter,
    AgentResponse,
)

logger = logging.getLogger(__name__)


class WebSocketAdapter(AgentAdapter):
    """Adapter for agents exposed over WebSocket / JSON-RPC (MCP protocol).

    Sends JSON-RPC 2.0 requests and collects the response, including any
    tool-call notifications that arrive before the final result.
    """

    def __init__(self, config: AdapterConfig) -> None:
        super().__init__(config)
        self._ws: ClientConnection | None = None
        self._request_id: int = 0

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        if self._connected:
            return
        extra_headers = {**self.config.headers}
        if self.config.auth:
            extra_headers["Authorization"] = self.config.auth
        try:
            self._ws = await ws_connect(
                self.config.endpoint,
                additional_headers=extra_headers,
                open_timeout=self.config.timeout_seconds,
            )
            self._connected = True
            logger.info("WebSocket connected to %s", self.config.endpoint)
        except Exception as exc:
            raise AdapterError(
                f"WebSocket connection to {self.config.endpoint} failed: {exc}"
            ) from exc

    async def disconnect(self) -> None:
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass  # best-effort
            finally:
                self._ws = None
                self._connected = False
                logger.info("WebSocket disconnected")

    # ------------------------------------------------------------------
    # Send / receive
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
        if not self._connected or self._ws is None:
            await self.connect()
        assert self._ws is not None

        self._request_id += 1
        request_id = str(self._request_id)

        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": "generate",
            "params": {"prompt": message},
        }
        if context:
            payload["params"]["context"] = context

        start = self._now_ms()
        tool_calls: list[dict[str, Any]] = []
        chunks: list[str] = []
        raw_messages: list[dict[str, Any]] = []

        try:
            await self._ws.send(json.dumps(payload))
        except Exception as exc:
            self._connected = False
            raise AdapterError(f"Failed to send WebSocket message: {exc}") from exc

        # Collect messages until we get the final JSON-RPC response.
        while True:
            remaining_ms = self.config.timeout_ms - self._elapsed_ms(start)
            if remaining_ms <= 0:
                raise AdapterTimeoutError(
                    f"WebSocket response timed out after {self.config.timeout_ms}ms"
                )

            try:
                raw = await asyncio.wait_for(
                    self._ws.recv(),
                    timeout=remaining_ms / 1000.0,
                )
            except asyncio.TimeoutError:
                raise AdapterTimeoutError(
                    f"WebSocket response timed out after {self.config.timeout_ms}ms"
                )
            except Exception as exc:
                self._connected = False
                raise AdapterError(f"WebSocket recv failed: {exc}") from exc

            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                # Non-JSON frame — treat as a text chunk.
                chunks.append(str(raw))
                continue

            raw_messages.append(msg)

            # JSON-RPC notification (tool call, progress, etc.)
            if "id" not in msg and msg.get("method") == "tool_call":
                params = msg.get("params", {})
                tool_calls.append({
                    "name": params.get("name", "unknown"),
                    "args": params.get("arguments", {}),
                    "result": params.get("result"),
                })
                continue

            # Streaming chunk notification.
            if "id" not in msg and msg.get("method") == "chunk":
                chunk_text = msg.get("params", {}).get("text", "")
                if chunk_text:
                    chunks.append(chunk_text)
                continue

            # Final response (has "id" matching our request).
            if msg.get("id") == request_id:
                latency = self._elapsed_ms(start)
                if "error" in msg:
                    err = msg["error"]
                    raise AdapterError(
                        f"JSON-RPC error {err.get('code')}: {err.get('message')}"
                    )
                result = msg.get("result", {})
                content = result.get("content", "") if isinstance(result, dict) else str(result)
                tokens = result.get("tokens_used", 0) if isinstance(result, dict) else 0

                return AgentResponse(
                    content=content,
                    tool_calls=tool_calls,
                    tokens_used=tokens,
                    latency_ms=latency,
                    chunks=chunks,
                    metadata={"request_id": request_id},
                    raw=raw_messages,
                )
