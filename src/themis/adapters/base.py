# Copyright (c) 2026 Reza Malik. Licensed under the Apache License, Version 2.0.
"""Base adapter for connecting to agents under test."""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class AdapterConfig:
    """Configuration for an agent adapter.

    The endpoint field is polymorphic — it can be a URL, a filesystem path,
    or a shell command, depending on the adapter type.
    """

    endpoint: str
    timeout_ms: int = 30_000
    max_retries: int = 0
    headers: dict[str, str] = field(default_factory=dict)
    auth: str | None = None

    @property
    def timeout_seconds(self) -> float:
        return self.timeout_ms / 1000.0


@dataclass
class AgentResponse:
    """Normalised response from any agent, regardless of transport.

    Every adapter produces one of these. Themis evaluation logic only ever
    touches AgentResponse — never raw transport objects.
    """

    content: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    tokens_used: int = 0
    latency_ms: float = 0.0
    chunks: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    raw: Any = None

    def __post_init__(self) -> None:
        # If no chunks were recorded, the whole content is the single chunk.
        if not self.chunks and self.content:
            self.chunks = [self.content]


class AdapterError(Exception):
    """Raised when an adapter encounters a transport-level failure."""


class AdapterTimeoutError(AdapterError):
    """Raised when an adapter call exceeds its configured timeout."""


class AgentAdapter(ABC):
    """Base class for agent test adapters.

    Adapters handle the transport layer — how to send a prompt to an agent
    and receive its response. Themis doesn't care about transport; she cares
    about the response quality.

    All adapters are async context managers::

        async with WebSocketAdapter(config) as agent:
            response = await agent.send("What is 2 + 2?")
    """

    def __init__(self, config: AdapterConfig) -> None:
        self.config = config
        self._connected = False

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    async def connect(self) -> None:
        """Establish the connection to the agent."""

    @abstractmethod
    async def send(self, message: str, context: dict[str, Any] | None = None) -> AgentResponse:
        """Send a prompt and return the normalised response."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Tear down the connection cleanly."""

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    async def __aenter__(self) -> AgentAdapter:
        await self.connect()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: Any,
    ) -> None:
        await self.disconnect()

    # ------------------------------------------------------------------
    # Helpers available to all adapters
    # ------------------------------------------------------------------

    @staticmethod
    def _now_ms() -> float:
        """High-resolution monotonic timestamp in milliseconds."""
        return time.monotonic() * 1000.0

    def _elapsed_ms(self, start_ms: float) -> float:
        return self._now_ms() - start_ms

    async def _send_with_retries(
        self,
        message: str,
        context: dict[str, Any] | None,
        send_fn: Any,
    ) -> AgentResponse:
        """Retry wrapper used by concrete adapters."""
        last_error: Exception | None = None
        attempts = 1 + self.config.max_retries

        for attempt in range(1, attempts + 1):
            try:
                return await send_fn(message, context)
            except AdapterTimeoutError:
                raise  # never retry timeouts
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "Adapter send attempt %d/%d failed: %s",
                    attempt,
                    attempts,
                    exc,
                )

        raise AdapterError(
            f"All {attempts} send attempts failed"
        ) from last_error
