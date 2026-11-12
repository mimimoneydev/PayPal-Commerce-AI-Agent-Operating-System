# Copyright 2026 PayPal Commerce AI Agent OS contributors
# SPDX-License-Identifier: Apache-2.0

"""The merchant portal's turn budgets: enough room to finish, few enough round trips
to stay responsive, and every knob tunable from the deployment environment."""

import pytest

from demo_common import merchant_latency_overrides

NAMES = (
    "MERCHANT_MAX_TOKENS",
    "MERCHANT_MAX_TOOL_ITERATIONS",
    "MERCHANT_MAX_ANALYSIS_ITERATIONS",
    "MERCHANT_ANALYSIS_TIMEOUT_S",
)


@pytest.fixture(autouse=True)
def clean_environment(monkeypatch):
    for name in NAMES:
        monkeypatch.delenv(name, raising=False)


def test_defaults_finish_the_answer_and_bound_the_round_trips():
    overrides = merchant_latency_overrides()
    assert overrides == {
        "max_tokens": 4096,
        "max_tool_iterations": 6,
        "max_analysis_iterations": 4,
        "analysis_timeout_s": 60.0,
    }
    # The old 2048 ceiling cut a multi-component merchant answer short.
    assert overrides["max_tokens"] > 2048
    assert overrides["max_analysis_iterations"] < 8


def test_every_budget_is_tunable(monkeypatch):
    monkeypatch.setenv("MERCHANT_MAX_TOKENS", "3072")
    monkeypatch.setenv("MERCHANT_MAX_TOOL_ITERATIONS", "3")
    monkeypatch.setenv("MERCHANT_MAX_ANALYSIS_ITERATIONS", "2")
    monkeypatch.setenv("MERCHANT_ANALYSIS_TIMEOUT_S", "12.5")
    assert merchant_latency_overrides() == {
        "max_tokens": 3072,
        "max_tool_iterations": 3,
        "max_analysis_iterations": 2,
        "analysis_timeout_s": 12.5,
    }


@pytest.mark.parametrize("bad", ["", "abc", "0", "-5"])
def test_bad_values_fall_back_to_the_safe_default(monkeypatch, bad):
    monkeypatch.setenv("MERCHANT_MAX_TOOL_ITERATIONS", bad)
    monkeypatch.setenv("MERCHANT_ANALYSIS_TIMEOUT_S", bad)
    overrides = merchant_latency_overrides()
    assert overrides["max_tool_iterations"] == 6
    assert overrides["analysis_timeout_s"] == 60.0
