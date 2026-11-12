# Copyright 2026 Anthropic PBC
# SPDX-License-Identifier: Apache-2.0

"""The ACME Mobile deployment's two agent configs."""

from __future__ import annotations

from commerce_common.model_provider import model_config_overrides
from demo_common import host_approval_default, merchant_auto_approve, merchant_latency_overrides
from merchant_agent import MerchantAgentConfig
from shopping_agent import ShoppingAgentConfig

_SHOPPING_DEFAULTS = ShoppingAgentConfig()
_MERCHANT_DEFAULTS = MerchantAgentConfig()

# Carrier vocabulary added to the policy-grounding lexicon.
_POLICY_TERMS = (
    "overage",
    "roaming",
    "data cap",
    "deprioritization",
    "early termination",
    "activation fee",
    "plan change",
    "upgrade fee",
    "upgrade cost",
    "cost to upgrade",
    "early upgrade",
    "upgrade early",
    "trade-in",
    "trade in",
    "autopay",
    "installment",
    "price guarantee",
)

# Carrier vocabulary added to the metrics-grounding lexicon.
_METRICS_TERMS = (
    "churn",
    "arpu",
    "net adds",
    "gross adds",
    "subscriber",
    "subscribers",
    "port-in",
    "port-ins",
    "port-out",
    "port-outs",
    "plan mix",
    "take rate",
    "deactivation",
    "deactivations",
)

# Regulated line items the assistant may never stage an edit to. The guardrail matches
# field names exactly, so each item's _usd spelling is listed as well.
_PROTECTED_FIELDS = (
    "activation_fee",
    "activation_fee_usd",
    "network_compliance_surcharge",
    "network_compliance_surcharge_usd",
    "regulatory_fee",
    "regulatory_fee_usd",
    "price_guarantee",
)


def build_shopping_config() -> ShoppingAgentConfig:
    return ShoppingAgentConfig(
        brand_name="ACME Mobile",
        assistant_name="ACME Assistant",
        brand_voice=(
            "plainspoken and precise — explains the bill like a good engineer, allergic to "
            "fine-print surprises"
        ),
        enable_disclosures=True,
        # The lineup is small and plan comparisons need every plan in one search.
        max_search_results=25,
        policy_intent_terms=_SHOPPING_DEFAULTS.policy_intent_terms + _POLICY_TERMS,
        **model_config_overrides(role="shopping"),
    )


def build_merchant_config(store_name: str) -> MerchantAgentConfig:
    return MerchantAgentConfig(
        brand_name=store_name,
        require_host_approval=host_approval_default(),
        auto_approve_changes=merchant_auto_approve(),
        approval_surface="the Approve button on the change preview card",
        metrics_intent_terms=_MERCHANT_DEFAULTS.metrics_intent_terms + _METRICS_TERMS,
        protected_fields=_MERCHANT_DEFAULTS.protected_fields + _PROTECTED_FIELDS,
        **model_config_overrides(role="merchant"),
        **merchant_latency_overrides(),
    )
