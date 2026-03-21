# Copyright (c) 2026 Reza Malik. Licensed under the Apache License, Version 2.0.
"""Themis tool modules.

Each tool is implemented in its own submodule and registered with the
FastMCP server via ``@mcp.tool()`` decorators in ``themis.server``.

Shared state (KnowledgeLoader) lives in
``themis.tools._shared`` and is imported by every tool module.
"""

from themis.tools.plan_test_strategy import plan_test_strategy
from themis.tools.judge_output import judge_output
from themis.tools.run_agent_test import run_agent_test
from themis.tools.evaluate_coverage import evaluate_coverage
from themis.tools.log_verdict import log_verdict

__all__ = [
    "plan_test_strategy",
    "judge_output",
    "run_agent_test",
    "evaluate_coverage",
    "log_verdict",
]
