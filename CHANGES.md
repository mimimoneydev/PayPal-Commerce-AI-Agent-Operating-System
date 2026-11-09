# Changes made for this project

This file records what was added for PayPal Commerce AI Agent OS relative to the
third-party Apache-2.0 baseline described in [CREDITS.md](CREDITS.md). It is
the change notice required by Apache-2.0 section 4(b) and the record of work
done during the PayPal AI Hackathon submission period (1 Oct - 12 Nov 2026).

**64 new files** were added; existing files were also modified. Local file
timestamps for the additions run from 16 Oct 2026 to 07 Nov 2026,
inside the submission period.

## What was added

- **PayPal Orders v2 payment layer** - OAuth, create/capture, `PayPal-Request-Id`
  idempotency, opaque checkout tokens, immutable cart snapshot with amount checks,
  webhook signature verification, durable payment/outbox state, Partner Referrals,
  and the accompanying docs and test suites (`commerce_common/payments.py`,
  `payment_store.py`, `paypal_partners.py`, `accounting.py`, `control_store.py`,
  `operations.py`, `docs/payments.md`, `docs/commerce-os.md`).
- **Commerce platform adapters** - WooCommerce bridge and Shopify webhooks, plus a
  full merchant/shopper platform example (`examples/commerce_platform/`,
  `integrations/woocommerce/`, `shopping_agent/woocommerce.py`, `shopify.py`).
- **Sponsor integrations** - Channel3 catalog search, AG Studio analytics
  workspace, Bryntum occupancy scheduler, and APIMatic-ready OpenAPI exports
  (`integrations/apimatic/`, `scripts/export_openapi.py`,
  `docs/sponsor-integrations.md`).
- **Model runtime and tooling** - OpenRouter model provider, connectivity check,
  infrastructure checks, and onboarding helpers.
- **Architecture diagram** - `docs/commerce-os-system-architecture.png`.

## New files by area

- `commerce-common/` - 12 files
- `docs/` - 6 files
- `examples/` - 33 files
- `integrations/` - 6 files
- `scripts/` - 3 files
- `shopping-agent/` - 4 files

## Full list

- `commerce-common/commerce_common/accounting.py`
- `commerce-common/commerce_common/control_store.py`
- `commerce-common/commerce_common/model_provider.py`
- `commerce-common/commerce_common/operations.py`
- `commerce-common/commerce_common/payment_store.py`
- `commerce-common/commerce_common/payments.py`
- `commerce-common/commerce_common/paypal_partners.py`
- `commerce-common/tests/test_model_provider.py`
- `commerce-common/tests/test_payment_recovery.py`
- `commerce-common/tests/test_payments.py`
- `commerce-common/tests/test_paypal_partners.py`
- `commerce-common/tests/test_postgres_integration.py`
- `docs/commerce-os-system-architecture.png`
- `docs/commerce-os.md`
- `docs/merchant-platform.md`
- `docs/payments.md`
- `docs/sponsor-integrations.md`
- `docs/woocommerce.md`
- `examples/commerce_platform/__init__.py`
- `examples/commerce_platform/admin.html`
- `examples/commerce_platform/admin.js`
- `examples/commerce_platform/app.py`
- `examples/commerce_platform/operations.py`
- `examples/commerce_platform/shopify_webhooks.py`
- `examples/commerce_platform/shopper.html`
- `examples/commerce_platform/shopper.js`
- `examples/commerce_platform/storefronts.py`
- `examples/commerce_platform/tests/test_platform.py`
- `examples/commerce_platform/tests/test_providers.py`
- `examples/demo_common/onboarding.py`
- `examples/demo_common/payments.py`
- `examples/demo_common/tests/test_payments.py`
- `examples/demo_common/tests/test_woocommerce_host.py`
- `examples/entertainment/merchant-web/next-env.d.ts`
- `examples/entertainment/storefront-web/next-env.d.ts`
- `examples/retail/api/channel3_catalog.py`
- `examples/retail/api/tests/test_channel3_catalog.py`
- `examples/retail/data/.memory-seeded.json`
- `examples/retail/data/.memory-store.json`
- `examples/retail/merchant-web/components/IntegrationBoundary.tsx`
- `examples/retail/merchant-web/components/analytics/AgStudioWorkspace.tsx`
- `examples/retail/merchant-web/components/views/AnalyticsView.tsx`
- `examples/retail/merchant-web/next-env.d.ts`
- `examples/retail/storefront-web/next-env.d.ts`
- `examples/telecom/merchant-web/next-env.d.ts`
- `examples/telecom/storefront-web/next-env.d.ts`
- `examples/travel/merchant-web/components/IntegrationBoundary.tsx`
- `examples/travel/merchant-web/components/schedule/BryntumOccupancyScheduler.tsx`
- `examples/travel/merchant-web/components/views/ScheduleView.tsx`
- `examples/travel/merchant-web/next-env.d.ts`
- `examples/travel/storefront-web/next-env.d.ts`
- `integrations/apimatic/README.md`
- `integrations/apimatic/entertainment/src/spec/openapi.json`
- `integrations/apimatic/retail/src/spec/openapi.json`
- `integrations/apimatic/telecom/src/spec/openapi.json`
- `integrations/apimatic/travel/src/spec/openapi.json`
- `integrations/woocommerce/agent-commerce-bridge.php`
- `scripts/check_commerce_infrastructure.py`
- `scripts/export_openapi.py`
- `scripts/test_openrouter.py`
- `shopping-agent/core/shopping_agent/shopify.py`
- `shopping-agent/core/shopping_agent/woocommerce.py`
- `shopping-agent/core/tests/test_shopify.py`
- `shopping-agent/core/tests/test_woocommerce.py`

Per-file change notices: the SPDX headers are retained on every source
file; this document is the repository-level record of changes. Add a short
'Modified for PayPal Commerce AI Agent OS' line to any further edited files.
