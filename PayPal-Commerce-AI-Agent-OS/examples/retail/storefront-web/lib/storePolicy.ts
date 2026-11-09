// Copyright 2026 Anthropic PBC
// SPDX-License-Identifier: Apache-2.0

/** Copied from ../data/policies.json; keep in sync with it. */
export const CONNECTED_STORE = ["woocommerce", "shopify"].includes(process.env.NEXT_PUBLIC_COMMERCE_PLATFORM ?? "demo");
export const STORE_POLICY = {
  returnsShort: CONNECTED_STORE ? "Ask about returns" : "30-day returns",
  returnsLine: CONNECTED_STORE ? "The store's returns policy applies. Ask the assistant for details." : "Most items can be returned within 30 days of delivery for a refund to your original payment method.",
  freeShippingThreshold: 49,
  standardShippingEta: CONNECTED_STORE ? "options at checkout" : "3–5 business days",
} as const;
