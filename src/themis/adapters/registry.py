# Copyright (c) 2026 Reza Malik. Licensed under the Apache License, Version 2.0.
"""Adapter registry — factory for creating adapters by name."""
from __future__ import annotations

import logging
from typing import Type

from .base import AdapterConfig, AdapterError, AgentAdapter
from .http import HTTPAdapter
from .stdio import StdioAdapter
from .stream import StreamAdapter
from .websocket import WebSocketAdapter

logger = logging.getLogger(__name__)

# Canonical registry of built-in adapter types.
ADAPTERS: dict[str, Type[AgentAdapter]] = {
    "websocket": WebSocketAdapter,
    "ws": WebSocketAdapter,
    "http": HTTPAdapter,
    "https": HTTPAdapter,
    "rest": HTTPAdapter,
    "stdio": StdioAdapter,
    "subprocess": StdioAdapter,
    "stream": StreamAdapter,
    "sse": StreamAdapter,
}


def create_adapter(adapter_type: str, config: AdapterConfig) -> AgentAdapter:
    """Instantiate an adapter by its registered name.

    Parameters
    ----------
    adapter_type:
        One of the keys in :data:`ADAPTERS` (case-insensitive).
    config:
        Connection configuration for the adapter.

    Returns
    -------
    AgentAdapter
        A concrete adapter instance, ready to be used as an async context
        manager.

    Raises
    ------
    AdapterError
        If ``adapter_type`` is not recognised.
    """
    key = adapter_type.lower().strip()
    cls = ADAPTERS.get(key)
    if cls is None:
        available = ", ".join(sorted(ADAPTERS))
        raise AdapterError(
            f"Unknown adapter type {adapter_type!r}. "
            f"Available types: {available}"
        )
    logger.debug("Creating %s adapter for %s", key, config.endpoint)
    return cls(config)


def register_adapter(name: str, cls: Type[AgentAdapter]) -> None:
    """Register a custom adapter type at runtime.

    This allows third-party code to extend Themis with new transport
    mechanisms without modifying the registry source.

    Parameters
    ----------
    name:
        Short identifier (e.g. ``"grpc"``).
    cls:
        A concrete subclass of :class:`AgentAdapter`.
    """
    if not issubclass(cls, AgentAdapter):
        raise TypeError(
            f"{cls.__name__} is not a subclass of AgentAdapter"
        )
    ADAPTERS[name.lower().strip()] = cls
    logger.info("Registered custom adapter: %s -> %s", name, cls.__name__)
