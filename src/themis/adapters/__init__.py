# Copyright (c) 2026 Reza Malik. Licensed under the Apache License, Version 2.0.
"""Themis adapter system — transport layer for reaching agents under test."""

from .base import AdapterConfig, AdapterError, AdapterTimeoutError, AgentAdapter, AgentResponse
from .http import HTTPAdapter
from .registry import ADAPTERS, create_adapter, register_adapter
from .stdio import StdioAdapter
from .stream import StreamAdapter
from .websocket import WebSocketAdapter

__all__ = [
    # Base types
    "AgentAdapter",
    "AgentResponse",
    "AdapterConfig",
    "AdapterError",
    "AdapterTimeoutError",
    # Concrete adapters
    "HTTPAdapter",
    "StdioAdapter",
    "StreamAdapter",
    "WebSocketAdapter",
    # Registry
    "ADAPTERS",
    "create_adapter",
    "register_adapter",
]
