# Copyright 2026 PayPal Commerce AI Agent OS contributors
# SPDX-License-Identifier: Apache-2.0

"""The retail deployment's model and turn-budget selection."""

from retail.api.agent_config import build_merchant_config, build_shopping_config


def test_merchant_can_pin_a_faster_model_without_changing_the_storefront(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("OPENROUTER_MODEL", "vendor/tool-model:free")
    monkeypatch.setenv("OPENROUTER_MERCHANT_MODEL", "vendor/fast-model:free")
    assert build_merchant_config("ACME").model == "vendor/fast-model:free"
    assert build_shopping_config().model == "vendor/tool-model:free"


def test_without_a_role_override_both_roles_keep_the_global_model(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("OPENROUTER_MODEL", "vendor/tool-model:free")
    monkeypatch.delenv("OPENROUTER_MERCHANT_MODEL", raising=False)
    monkeypatch.delenv("OPENROUTER_SHOPPING_MODEL", raising=False)
    assert build_merchant_config("ACME").model == "vendor/tool-model:free"
    assert build_shopping_config().model == "vendor/tool-model:free"


def test_merchant_config_gets_the_bounded_turn_budgets(monkeypatch):
    for name in (
        "MERCHANT_MAX_TOKENS",
        "MERCHANT_MAX_TOOL_ITERATIONS",
        "MERCHANT_MAX_ANALYSIS_ITERATIONS",
        "MERCHANT_ANALYSIS_TIMEOUT_S",
    ):
        monkeypatch.delenv(name, raising=False)
    config = build_merchant_config("ACME")
    assert config.max_tokens == 4096
    assert config.max_tool_iterations == 6
    assert config.max_analysis_iterations == 4
    assert config.analysis_timeout_s == 60.0
