# Copyright (c) 2026 Reza Malik. Licensed under the Apache License, Version 2.0.
"""MCP tool: judge_output

Evaluate an agent's actual output against expected output using multiple
comparison strategies.  Pure Python — no embeddings, no external services.

This is Themis's core judgement engine.  Every comparison strategy is
deterministic and reproducible.
"""

from __future__ import annotations

import json
import re
from typing import Any

from themis.tools._shared import coerce, emit_event


# ---------------------------------------------------------------------------
# Token overlap similarity — pure Python, no embeddings
# ---------------------------------------------------------------------------

def _tokenize(text: str) -> list[str]:
    """Split text into lowercase alphanumeric tokens."""
    return re.findall(r"[a-z0-9]+", text.lower())


def _token_overlap_ratio(a: str, b: str) -> float:
    """Compute token overlap ratio (Jaccard-like) between two strings.

    Returns a value in [0.0, 1.0].
    """
    tokens_a = set(_tokenize(a))
    tokens_b = set(_tokenize(b))
    if not tokens_a and not tokens_b:
        return 1.0
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


# ---------------------------------------------------------------------------
# JSON structure comparison
# ---------------------------------------------------------------------------

def _json_structure_match(expected: str, actual: str) -> tuple[bool, list[str]]:
    """Compare JSON structures — keys and types, not exact values.

    Returns (match, deviations).
    """
    deviations: list[str] = []
    try:
        expected_obj = json.loads(expected) if isinstance(expected, str) else expected
    except (json.JSONDecodeError, TypeError):
        deviations.append("expected_output is not valid JSON")
        return False, deviations

    try:
        actual_obj = json.loads(actual) if isinstance(actual, str) else actual
    except (json.JSONDecodeError, TypeError):
        deviations.append("actual_output is not valid JSON")
        return False, deviations

    def _compare(exp: Any, act: Any, path: str = "$") -> None:
        if type(exp) is not type(act):
            deviations.append(
                f"{path}: expected type {type(exp).__name__}, got {type(act).__name__}"
            )
            return

        if isinstance(exp, dict):
            exp_keys = set(exp.keys())
            act_keys = set(act.keys())
            for missing in exp_keys - act_keys:
                deviations.append(f"{path}.{missing}: missing key")
            for extra in act_keys - exp_keys:
                deviations.append(f"{path}.{extra}: unexpected key")
            for key in exp_keys & act_keys:
                _compare(exp[key], act[key], f"{path}.{key}")

        elif isinstance(exp, list):
            if len(exp) != len(act):
                deviations.append(
                    f"{path}: expected list length {len(exp)}, got {len(act)}"
                )
            for i in range(min(len(exp), len(act))):
                _compare(exp[i], act[i], f"{path}[{i}]")

    _compare(expected_obj, actual_obj)
    return len(deviations) == 0, deviations


# ---------------------------------------------------------------------------
# Tool call sequence validation
# ---------------------------------------------------------------------------

def _validate_tool_calls(
    expected_calls: list[dict[str, Any]],
    actual_calls: list[dict[str, Any]],
) -> tuple[bool, float, list[str]]:
    """Validate tool call sequences.

    Each call dict should have at minimum: {name: str}
    Optionally: {name: str, arguments: dict}

    Returns (match, score, deviations).
    """
    deviations: list[str] = []

    if not expected_calls and not actual_calls:
        return True, 1.0, []

    if not expected_calls:
        deviations.append(f"No tool calls expected but {len(actual_calls)} were made")
        return False, 0.0, deviations

    if not actual_calls:
        deviations.append(
            f"Expected {len(expected_calls)} tool calls but none were made"
        )
        return False, 0.0, deviations

    # Check sequence length
    if len(expected_calls) != len(actual_calls):
        deviations.append(
            f"Expected {len(expected_calls)} tool calls, got {len(actual_calls)}"
        )

    matches = 0
    total = max(len(expected_calls), len(actual_calls))

    for i in range(min(len(expected_calls), len(actual_calls))):
        exp = expected_calls[i]
        act = actual_calls[i]
        exp_name = exp.get("name", "")
        act_name = act.get("name", "")

        if exp_name != act_name:
            deviations.append(
                f"Tool call [{i}]: expected '{exp_name}', got '{act_name}'"
            )
            continue

        # Name matches — check arguments if provided
        exp_args = exp.get("arguments", {})
        act_args = act.get("arguments", {})

        if exp_args:
            arg_match = True
            for key, val in exp_args.items():
                if key not in act_args:
                    deviations.append(
                        f"Tool call [{i}] '{exp_name}': missing argument '{key}'"
                    )
                    arg_match = False
                elif act_args[key] != val:
                    deviations.append(
                        f"Tool call [{i}] '{exp_name}': argument '{key}' "
                        f"expected {val!r}, got {act_args[key]!r}"
                    )
                    arg_match = False

            if arg_match:
                matches += 1
            else:
                matches += 0.5  # partial credit for correct name
        else:
            matches += 1

    score = matches / total if total > 0 else 1.0
    all_match = len(deviations) == 0
    return all_match, score, deviations


# ---------------------------------------------------------------------------
# Main tool
# ---------------------------------------------------------------------------

def judge_output(
    test_case: dict,
    actual_output: str,
    criteria: dict | None = None,
    conn: object = None,
) -> dict:
    """Judge an agent's actual output against the expected test case.

    Args:
        test_case: Dict with keys:
            - ``input`` (str): The prompt/input sent to the agent.
            - ``expected_output`` (str): The expected response (or pattern).
            - ``expected_pattern`` (str): Regex pattern the output must match.
            - ``test_type`` (str): One of "exact", "contains", "similarity",
              "json_structure", "tool_calls", "regex", "composite".
            - ``expected_tool_calls`` (list[dict]): Expected tool call sequence.
            - ``token_budget`` (int): Maximum allowed tokens.
        actual_output: The agent's actual response text.
        criteria: Optional overrides:
            - ``exact_match`` (bool): Require exact string match.
            - ``contains`` (list[str]): Strings that must appear in output.
            - ``similarity_threshold`` (float): Minimum token overlap ratio.
            - ``tool_calls_match`` (bool): Validate tool call sequence.
            - ``json_structure`` (bool): Validate JSON structure match.
            - ``regex_pattern`` (str): Override regex pattern.
            - ``case_sensitive`` (bool): Whether comparisons are case-sensitive.
        conn: Kuzu/LadybugDB connection for graph mode, or None.

    Returns:
        Dict with keys: verdict, score, deviations, tool_call_analysis,
        token_usage_analysis, checks_performed.
    """
    test_case = coerce(test_case, dict) or {}
    criteria = coerce(criteria, dict) or {}

    expected_output: str = test_case.get("expected_output", "")
    expected_pattern: str = test_case.get("expected_pattern", "")
    test_type: str = test_case.get("test_type", "similarity")
    expected_tool_calls: list = test_case.get("expected_tool_calls", [])
    token_budget: int | None = test_case.get("token_budget")
    actual_tokens: int = test_case.get("actual_tokens_used", 0)

    case_sensitive: bool = criteria.get("case_sensitive", True)
    similarity_threshold: float = criteria.get("similarity_threshold", 0.7)

    deviations: list[str] = []
    checks_performed: list[str] = []
    scores: list[float] = []

    # Normalise for case-insensitive comparison
    cmp_expected = expected_output if case_sensitive else expected_output.lower()
    cmp_actual = actual_output if case_sensitive else actual_output.lower()

    # ----- Exact match -----
    if test_type == "exact" or criteria.get("exact_match"):
        checks_performed.append("exact_match")
        if cmp_actual == cmp_expected:
            scores.append(1.0)
        else:
            scores.append(0.0)
            # Show first divergence point for debugging
            for i, (a, b) in enumerate(zip(cmp_actual, cmp_expected)):
                if a != b:
                    deviations.append(
                        f"First difference at position {i}: "
                        f"expected {b!r}, got {a!r}"
                    )
                    break
            else:
                if len(cmp_actual) != len(cmp_expected):
                    deviations.append(
                        f"Length mismatch: expected {len(cmp_expected)}, "
                        f"got {len(cmp_actual)}"
                    )

    # ----- Contains check -----
    if test_type == "contains" or criteria.get("contains"):
        checks_performed.append("contains")
        must_contain = criteria.get("contains", [])
        if not must_contain and expected_output:
            # Default: the expected output itself must be contained
            must_contain = [expected_output]

        found_count = 0
        for needle in must_contain:
            needle_cmp = needle if case_sensitive else needle.lower()
            if needle_cmp in cmp_actual:
                found_count += 1
            else:
                deviations.append(f"Missing required content: {needle!r}")

        if must_contain:
            scores.append(found_count / len(must_contain))
        else:
            scores.append(1.0)

    # ----- Similarity (token overlap) -----
    if test_type == "similarity" or (
        test_type == "composite" and expected_output
    ):
        checks_performed.append("token_overlap_similarity")
        sim = _token_overlap_ratio(expected_output, actual_output)
        scores.append(sim)
        if sim < similarity_threshold:
            deviations.append(
                f"Token overlap similarity {sim:.3f} below "
                f"threshold {similarity_threshold:.3f}"
            )

    # ----- JSON structure match -----
    if test_type == "json_structure" or criteria.get("json_structure"):
        checks_performed.append("json_structure")
        match, json_devs = _json_structure_match(expected_output, actual_output)
        scores.append(1.0 if match else max(0.0, 1.0 - len(json_devs) * 0.1))
        deviations.extend(json_devs)

    # ----- Regex pattern match -----
    regex_pat = criteria.get("regex_pattern") or expected_pattern
    if test_type == "regex" or regex_pat:
        checks_performed.append("regex_pattern")
        try:
            flags = 0 if case_sensitive else re.IGNORECASE
            if re.search(regex_pat, actual_output, flags):
                scores.append(1.0)
            else:
                scores.append(0.0)
                deviations.append(
                    f"Output does not match regex pattern: {regex_pat!r}"
                )
        except re.error as e:
            scores.append(0.0)
            deviations.append(f"Invalid regex pattern: {e}")

    # ----- Tool call validation -----
    tool_call_analysis: dict[str, Any] | None = None
    actual_tool_calls: list = test_case.get("actual_tool_calls", [])
    if test_type == "tool_calls" or criteria.get("tool_calls_match") or expected_tool_calls:
        checks_performed.append("tool_call_sequence")
        tc_match, tc_score, tc_devs = _validate_tool_calls(
            expected_tool_calls, actual_tool_calls,
        )
        scores.append(tc_score)
        deviations.extend(tc_devs)
        tool_call_analysis = {
            "expected_count": len(expected_tool_calls),
            "actual_count": len(actual_tool_calls),
            "sequence_match": tc_match,
            "score": round(tc_score, 3),
            "deviations": tc_devs,
        }

    # ----- Token usage analysis -----
    token_usage_analysis: dict[str, Any] | None = None
    if token_budget is not None:
        checks_performed.append("token_budget")
        exceeded = actual_tokens > token_budget
        usage_ratio = actual_tokens / token_budget if token_budget > 0 else 0.0
        if exceeded:
            deviations.append(
                f"Token budget exceeded: used {actual_tokens}, "
                f"budget was {token_budget} ({usage_ratio:.1%})"
            )
            scores.append(max(0.0, 1.0 - (usage_ratio - 1.0)))
        else:
            scores.append(1.0)

        token_usage_analysis = {
            "budget": token_budget,
            "used": actual_tokens,
            "ratio": round(usage_ratio, 3),
            "exceeded": exceeded,
        }

    # ----- Compute final score and verdict -----
    if not scores:
        # No checks were applicable — default to similarity
        checks_performed.append("token_overlap_similarity_fallback")
        sim = _token_overlap_ratio(expected_output, actual_output)
        scores.append(sim)
        if sim < similarity_threshold:
            deviations.append(
                f"Fallback similarity {sim:.3f} below threshold {similarity_threshold:.3f}"
            )

    final_score = sum(scores) / len(scores)

    if final_score >= 0.95:
        verdict = "pass"
    elif final_score >= 0.6:
        verdict = "warning"
    else:
        verdict = "fail"

    result: dict[str, Any] = {
        "verdict": verdict,
        "score": round(final_score, 4),
        "deviations": deviations,
        "checks_performed": checks_performed,
    }

    if tool_call_analysis is not None:
        result["tool_call_analysis"] = tool_call_analysis

    if token_usage_analysis is not None:
        result["token_usage_analysis"] = token_usage_analysis

    emit_event("judge_output", {
        "test_type": test_type,
        "verdict": verdict,
        "score": round(final_score, 4),
        "checks_count": len(checks_performed),
        "deviations_count": len(deviations),
    })

    return result
