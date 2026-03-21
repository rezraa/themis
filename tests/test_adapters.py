# Copyright (c) 2026 Reza Malik. Licensed under the Apache License, Version 2.0.
"""Tests for Themis adapter system — base types, registry, config."""

from __future__ import annotations

import pytest

from themis.adapters.base import AgentAdapter, AgentResponse, AdapterConfig
from themis.adapters.registry import create_adapter, ADAPTERS, register_adapter


class TestAdapterConfig:
    """Test adapter configuration."""

    def test_default_config(self):
        config = AdapterConfig(endpoint="http://localhost:8000")
        assert config.timeout_ms == 30000
        assert config.max_retries == 0
        assert config.headers == {}
        assert config.auth is None

    def test_custom_config(self):
        config = AdapterConfig(
            endpoint="ws://localhost:9000",
            timeout_ms=5000,
            max_retries=3,
            headers={"X-API-Key": "test"},
            auth="Bearer token123",
        )
        assert config.timeout_ms == 5000
        assert config.max_retries == 3
        assert config.headers["X-API-Key"] == "test"


class TestAgentResponse:
    """Test response dataclass."""

    def test_basic_response(self):
        resp = AgentResponse(
            content="Hello world",
            tool_calls=[],
            tokens_used=10,
            latency_ms=150.0,
            chunks=["Hello world"],
            metadata={},
            raw=None,
        )
        assert resp.content == "Hello world"
        assert resp.tokens_used == 10
        assert resp.latency_ms == 150.0


class TestRegistry:
    """Test adapter registry."""

    def test_all_adapters_registered(self):
        assert "websocket" in ADAPTERS
        assert "http" in ADAPTERS
        assert "stdio" in ADAPTERS
        assert "stream" in ADAPTERS

    def test_aliases_registered(self):
        assert "ws" in ADAPTERS
        assert "rest" in ADAPTERS
        assert "sse" in ADAPTERS

    def test_create_adapter(self):
        config = AdapterConfig(endpoint="http://localhost:8000")
        adapter = create_adapter("http", config)
        assert isinstance(adapter, AgentAdapter)

    def test_create_with_alias(self):
        config = AdapterConfig(endpoint="ws://localhost:9000")
        adapter = create_adapter("ws", config)
        assert isinstance(adapter, AgentAdapter)

    def test_unknown_adapter_raises(self):
        from themis.adapters.base import AdapterError
        config = AdapterConfig(endpoint="test")
        with pytest.raises(AdapterError, match="Unknown adapter"):
            create_adapter("nonexistent", config)

    def test_register_custom_adapter(self):
        class CustomAdapter(AgentAdapter):
            def __init__(self, config):
                self.config = config

            async def connect(self):
                pass

            async def send(self, message, context=None):
                return AgentResponse(
                    content="custom", tool_calls=[], tokens_used=0,
                    latency_ms=0, chunks=["custom"], metadata={}, raw=None,
                )

            async def disconnect(self):
                pass

        register_adapter("custom", CustomAdapter)
        assert "custom" in ADAPTERS

        config = AdapterConfig(endpoint="custom://test")
        adapter = create_adapter("custom", config)
        assert isinstance(adapter, CustomAdapter)
