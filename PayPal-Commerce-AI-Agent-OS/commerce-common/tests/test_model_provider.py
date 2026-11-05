# Copyright 2026 Anthropic PBC
# SPDX-License-Identifier: Apache-2.0

from commerce_common.model_provider import (
    OPENROUTER_BASE_URL,
    OPENROUTER_FREE_MODEL,
    agent_sdk_environment,
    build_model_client,
    model_config_overrides,
)


def test_openrouter_free_router_configures_main_and_memory_models(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    assert model_config_overrides() == {
        "model": OPENROUTER_FREE_MODEL,
        "memory_model": OPENROUTER_FREE_MODEL,
        "thinking_effort": None,
        "send_thinking_controls": False,
    }


def test_openrouter_models_are_selectable_independently(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("OPENROUTER_MODEL", "vendor/tool-model:free")
    monkeypatch.setenv("OPENROUTER_MEMORY_MODEL", "vendor/small-model:free")
    overrides = model_config_overrides()
    assert overrides["model"] == "vendor/tool-model:free"
    assert overrides["memory_model"] == "vendor/small-model:free"


async def test_messages_client_uses_openrouter_bearer_auth_and_attribution(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    monkeypatch.setenv("OPENROUTER_SITE_URL", "https://shop.example")
    monkeypatch.setenv("OPENROUTER_APP_NAME", "Example shop")
    client = build_model_client(30)
    assert str(client.base_url) == f"{OPENROUTER_BASE_URL}/"
    assert client.auth_token == "sk-or-test"
    assert client.api_key is None
    assert client.default_headers["HTTP-Referer"] == "https://shop.example"
    assert client.default_headers["X-Title"] == "Example shop"
    await client.close()


def test_agent_sdk_receives_the_anthropic_compatible_openrouter_environment(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-test")
    assert agent_sdk_environment() == {
        "ANTHROPIC_BASE_URL": OPENROUTER_BASE_URL,
        "ANTHROPIC_AUTH_TOKEN": "sk-or-test",
        "ANTHROPIC_API_KEY": "",
    }


def test_no_openrouter_key_leaves_existing_provider_configuration_alone(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    assert model_config_overrides() == {}
    assert agent_sdk_environment() == {}
