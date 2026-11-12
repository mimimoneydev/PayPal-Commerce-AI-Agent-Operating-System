# Copyright 2026 Anthropic PBC
# SPDX-License-Identifier: Apache-2.0

"""Provider selection for Anthropic-compatible model endpoints.

OpenRouter exposes an Anthropic Messages-compatible endpoint, so the turn loops retain
their native streaming and tool protocol. Only client construction, model names, and
optional request controls vary by provider.
"""

from __future__ import annotations

import os
from typing import Any, Literal

from anthropic import AsyncAnthropic

OPENROUTER_BASE_URL = "https://openrouter.ai/api"
OPENROUTER_DEFAULT_MODEL = "deepseek/deepseek-v4.1-flash"
# Kept as a compatibility alias for callers that imported the old constant. The default
# is now pinned so tool behavior is reproducible across shopping, merchant, memory, and
# analysis calls instead of depending on OpenRouter's rotating free router.
OPENROUTER_FREE_MODEL = OPENROUTER_DEFAULT_MODEL


def openrouter_enabled() -> bool:
    return bool(os.environ.get("OPENROUTER_API_KEY", "").strip())


def model_config_overrides(
    role: Literal["shopping", "merchant"] | None = None,
) -> dict[str, Any]:
    """Config overrides for the selected demo provider.

    OpenRouter defaults to DeepSeek V4.1 Flash. Provider-specific thinking controls are
    omitted because the Anthropic-compatible endpoint does not accept Anthropic's native
    thinking block controls for every routed model.

    ``OPENROUTER_SHOPPING_MODEL`` and ``OPENROUTER_MERCHANT_MODEL`` override the global
    model for one role only: a merchant turn carries a larger prompt and more tools, so a
    deployment can pin a faster model there without changing the storefront's behavior.
    An unset role-specific variable keeps ``OPENROUTER_MODEL``.
    """
    if not openrouter_enabled():
        return {}
    global_model = os.environ.get("OPENROUTER_MODEL", OPENROUTER_DEFAULT_MODEL).strip()
    role_model = os.environ.get(f"OPENROUTER_{role.upper()}_MODEL", "").strip() if role else ""
    model = role_model or global_model
    memory_model = os.environ.get("OPENROUTER_MEMORY_MODEL", model).strip()
    return {
        "model": model,
        "memory_model": memory_model,
        "thinking_effort": None,
        "send_thinking_controls": False,
    }


def build_model_client(timeout_s: float) -> AsyncAnthropic:
    """Build the Messages client for OpenRouter or the Anthropic default."""
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        return AsyncAnthropic(timeout=timeout_s)
    headers = {
        "X-Title": os.environ.get("OPENROUTER_APP_NAME", "PayPal Commerce AI Agent OS"),
    }
    if site_url := os.environ.get("OPENROUTER_SITE_URL", "").strip():
        headers["HTTP-Referer"] = site_url
    return AsyncAnthropic(
        auth_token=key,
        base_url=os.environ.get("OPENROUTER_BASE_URL", OPENROUTER_BASE_URL),
        timeout=timeout_s,
        default_headers=headers,
    )


def agent_sdk_environment() -> dict[str, str]:
    """Environment passed to the Agent SDK's Claude Code child process."""
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        return {}
    return {
        "ANTHROPIC_BASE_URL": os.environ.get("OPENROUTER_BASE_URL", OPENROUTER_BASE_URL),
        "ANTHROPIC_AUTH_TOKEN": key,
        # Claude Code gives ANTHROPIC_API_KEY precedence; it must be explicitly empty.
        "ANTHROPIC_API_KEY": "",
    }


def provider_has_credentials() -> bool:
    return openrouter_enabled() or bool(
        os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    )


def provider_label() -> str:
    return "OpenRouter" if openrouter_enabled() else "Anthropic"
