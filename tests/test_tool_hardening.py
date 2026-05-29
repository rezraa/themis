# Copyright (c) 2026 Reza Malik. Licensed under the Apache License, Version 2.0.
"""E2/S6 hardening tests — failure shapes from the S5 post-mortem matrix.

Covers coerce() container-default behaviour and plan_test_strategy's
lone-string remap plus its fail-loud handling of a missing required signal.
"""

from __future__ import annotations

import pytest

from themis.tools._shared import coerce, coerce_or_raise
from themis.tools.plan_test_strategy import plan_test_strategy
from themis.tools.log_verdict import log_verdict


class TestCoerce:

    def test_str_to_dict_mismatch_returns_default(self):
        assert coerce("production", dict, default={}) == {}

    def test_list_where_dict_expected_returns_default(self):
        assert coerce(["a"], dict, default={}) == {}

    def test_json_string_to_list(self):
        assert coerce("[1,2]", list, default=[]) == [1, 2]

    def test_native_dict_passthrough(self):
        assert coerce({"k": 1}, dict) == {"k": 1}

    def test_none_returns_default(self):
        assert coerce(None, dict, default={}) == {}

    def test_two_arg_call_still_works(self):
        assert coerce("[1]", list) == [1]


class TestCoerceOrRaise:
    """Persist-safe variant backing log_verdict's ``details`` field."""

    def test_none_returns_empty_default(self):
        assert coerce_or_raise(None, dict, {}) == {}

    def test_native_dict_passthrough(self):
        assert coerce_or_raise({"k": 1}, dict, {}) == {"k": 1}

    def test_json_object_string(self):
        assert coerce_or_raise('{"k": 1}', dict, {}) == {"k": 1}

    def test_nonempty_wrong_type_raises(self):
        # A list where a dict is expected must fail loud, not become {}.
        with pytest.raises(TypeError):
            coerce_or_raise(["a"], dict, {})

    def test_bare_nonjson_string_raises(self):
        with pytest.raises(TypeError):
            coerce_or_raise("production", dict, {})


class TestLogVerdictPersistedDetails:
    """``details`` is persisted -> coerce_or_raise contract."""

    def test_none_details_ok(self):
        result = log_verdict("audit", "sysX", "pass", details=None)
        assert result["logged"] is True

    def test_dict_details_ok(self):
        result = log_verdict("audit", "sysX", "pass", details={"test_count": 3})
        assert result["logged"] is True

    def test_json_string_details_ok(self):
        result = log_verdict(
            "audit", "sysX", "pass", details='{"test_count": 3}'
        )
        assert result["logged"] is True

    def test_nonempty_wrong_type_details_raises(self):
        # A list where a dict is expected must NOT be swallowed into {}.
        with pytest.raises(TypeError):
            log_verdict("audit", "sysX", "pass", details=["oops"])

    def test_bare_nonjson_string_details_raises(self):
        with pytest.raises(TypeError):
            log_verdict("audit", "sysX", "pass", details="production")


class TestPlanTestStrategyHardening:

    def test_truthy_wrong_type_constraints_does_not_crash(self):
        # A bare string where constraints expects a dict used to survive
        # `coerce(...) or {}` and crash on `.get()`.
        result = plan_test_strategy(
            system_description="REST API",
            structural_signals=["rest-api"],
            constraints="production",
        )
        assert isinstance(result, dict)

    def test_missing_structural_signals_raises(self):
        with pytest.raises(TypeError, match="structural_signals"):
            plan_test_strategy(system_description="REST API")

    def test_missing_system_description_raises(self):
        with pytest.raises(TypeError):
            plan_test_strategy(structural_signals=["rest-api"])

    def test_lone_stray_string_maps_to_system_description(self):
        # Exactly one stray string + no system_description -> recovered.
        result = plan_test_strategy(
            structural_signals=["rest-api"],
            target="A REST API under test",
        )
        assert isinstance(result, dict)

    def test_genuinely_unknown_kwarg_raises(self):
        with pytest.raises(TypeError):
            plan_test_strategy(
                system_description="x",
                structural_signals=["rest-api"],
                bogus={"not": "a string"},
            )
