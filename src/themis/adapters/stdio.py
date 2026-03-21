# Copyright (c) 2026 Reza Malik. Licensed under the Apache License, Version 2.0.
"""Stdio adapter — connects to CLI agents via subprocess."""
from __future__ import annotations

import asyncio
import json
import logging
import shlex
from typing import Any

from .base import (
    AdapterConfig,
    AdapterError,
    AdapterTimeoutError,
    AgentAdapter,
    AgentResponse,
)

logger = logging.getLogger(__name__)


class StdioAdapter(AgentAdapter):
    """Adapter for agents launched as local subprocesses.

    The ``endpoint`` in :class:`AdapterConfig` is treated as a shell command
    (e.g. ``"python -m my_agent"`` or ``"/usr/local/bin/my-agent --json"``).

    Communication happens over stdin/stdout.  Each :meth:`send` call writes
    one line of JSON to stdin and reads lines from stdout until the process
    emits a blank line or the timeout expires.  stderr output is captured
    but not treated as the agent's answer — it is stored in
    :pyattr:`AgentResponse.metadata["stderr"]`.

    Two operating modes:

    * **persistent** (default) — The subprocess is started once on
      :meth:`connect` and kept alive across multiple :meth:`send` calls.
    * **one-shot** — Set ``config.headers["mode"] = "oneshot"`` and the
      adapter will spawn a fresh process for every :meth:`send`.
    """

    def __init__(self, config: AdapterConfig) -> None:
        super().__init__(config)
        self._proc: asyncio.subprocess.Process | None = None
        self._oneshot = config.headers.get("mode", "").lower() == "oneshot"

    # ------------------------------------------------------------------
    # Connection lifecycle
    # ------------------------------------------------------------------

    async def connect(self) -> None:
        if self._connected:
            return
        if not self._oneshot:
            self._proc = await self._spawn()
        self._connected = True
        logger.info("Stdio adapter ready: %s", self.config.endpoint)

    async def disconnect(self) -> None:
        await self._kill()
        self._connected = False
        logger.info("Stdio adapter closed")

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
        if not self._connected:
            await self.connect()

        proc = self._proc
        if self._oneshot or proc is None or proc.returncode is not None:
            proc = await self._spawn()
            if not self._oneshot:
                self._proc = proc

        payload = json.dumps({"prompt": message, **({"context": context} if context else {})})

        start = self._now_ms()
        stdout_lines: list[str] = []
        stderr_text = ""

        try:
            assert proc.stdin is not None
            proc.stdin.write((payload + "\n").encode())
            await proc.stdin.drain()

            if self._oneshot:
                # Wait for the process to exit.
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=self.config.timeout_seconds,
                )
                stdout_lines = stdout_bytes.decode(errors="replace").splitlines()
                stderr_text = stderr_bytes.decode(errors="replace")
            else:
                # Persistent mode: read until a blank line or timeout.
                assert proc.stdout is not None
                deadline = self.config.timeout_seconds
                while True:
                    remaining = deadline - (self._elapsed_ms(start) / 1000.0)
                    if remaining <= 0:
                        raise asyncio.TimeoutError
                    line_bytes = await asyncio.wait_for(
                        proc.stdout.readline(),
                        timeout=remaining,
                    )
                    line = line_bytes.decode(errors="replace").rstrip("\n")
                    if line == "":
                        # Blank line = end of response.
                        break
                    stdout_lines.append(line)

                # Drain any available stderr (non-blocking).
                stderr_text = await self._read_stderr(proc)

        except asyncio.TimeoutError:
            if self._oneshot:
                await self._terminate(proc)
            raise AdapterTimeoutError(
                f"Stdio response timed out after {self.config.timeout_ms}ms"
            )
        except Exception as exc:
            raise AdapterError(f"Stdio communication failed: {exc}") from exc
        finally:
            if self._oneshot and proc.returncode is None:
                await self._terminate(proc)

        latency = self._elapsed_ms(start)
        content, tool_calls, tokens, metadata = self._parse_output(stdout_lines)

        if stderr_text:
            metadata["stderr"] = stderr_text
        if proc.returncode is not None:
            metadata["exit_code"] = proc.returncode

        return AgentResponse(
            content=content,
            tool_calls=tool_calls,
            tokens_used=tokens,
            latency_ms=latency,
            chunks=stdout_lines,
            metadata=metadata,
            raw=stdout_lines,
        )

    # ------------------------------------------------------------------
    # Process management
    # ------------------------------------------------------------------

    async def _spawn(self) -> asyncio.subprocess.Process:
        args = shlex.split(self.config.endpoint)
        try:
            proc = await asyncio.create_subprocess_exec(
                *args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise AdapterError(
                f"Command not found: {args[0]!r}"
            ) from exc
        except Exception as exc:
            raise AdapterError(
                f"Failed to spawn subprocess: {exc}"
            ) from exc
        logger.debug("Spawned process %d: %s", proc.pid, self.config.endpoint)
        return proc

    async def _terminate(self, proc: asyncio.subprocess.Process) -> None:
        """Gracefully terminate, then kill if needed."""
        if proc.returncode is not None:
            return
        try:
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
        except ProcessLookupError:
            pass

    async def _kill(self) -> None:
        if self._proc is not None:
            await self._terminate(self._proc)
            self._proc = None

    @staticmethod
    async def _read_stderr(proc: asyncio.subprocess.Process) -> str:
        """Non-blocking drain of stderr."""
        assert proc.stderr is not None
        parts: list[str] = []
        while True:
            try:
                chunk = await asyncio.wait_for(proc.stderr.read(4096), timeout=0.05)
                if not chunk:
                    break
                parts.append(chunk.decode(errors="replace"))
            except asyncio.TimeoutError:
                break
        return "".join(parts)

    # ------------------------------------------------------------------
    # Output parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_output(
        lines: list[str],
    ) -> tuple[str, list[dict[str, Any]], int, dict[str, Any]]:
        """Try to parse structured JSON output; fall back to plain text."""
        combined = "\n".join(lines)
        tool_calls: list[dict[str, Any]] = []
        tokens = 0
        metadata: dict[str, Any] = {}

        # Try JSON first.
        try:
            data = json.loads(combined)
            if isinstance(data, dict):
                content = str(
                    data.get("content", "")
                    or data.get("response", "")
                    or data.get("text", "")
                    or combined
                )
                tool_calls = data.get("tool_calls", [])
                usage = data.get("usage", {})
                if isinstance(usage, dict):
                    tokens = usage.get("total_tokens", 0)
                metadata["format"] = "json"
                return content, tool_calls, tokens, metadata
        except (json.JSONDecodeError, ValueError):
            pass

        metadata["format"] = "text"
        return combined, tool_calls, tokens, metadata
