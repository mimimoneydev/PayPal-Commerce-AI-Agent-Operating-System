# Hackathon sponsor integrations

These integrations are additive. With no sponsor credentials, the existing storefronts,
merchant tools, checkout, and approval workflow continue to operate on their built-in data.

## Channel3: retail product discovery

Set `CHANNEL3_API_KEY` to make the retail storefront search Channel3 in addition to the
local catalog. `CHANNEL3_BASE_URL` defaults to `https://api.trychannel3.com`; the adapter
calls its `/v1/search` and `/v1/products/{id}` routes and reads Channel3's paginated
`data` response envelope.

- The API key remains in the Python host and is never sent to the browser or model.
- Search results are normalized into the existing `ProductDetails` contract and retain a
  `ch3:` namespace so they cannot collide with local SKUs.
- Channel3 failures, timeouts, or invalid responses fall back to the local catalog.
- Merchant tools intentionally stay on the authoritative local merchant catalog.
- The demo can add a discovered offer to its sandbox cart. A production deployment must
  re-fetch the authoritative offer and revalidate price, availability, seller, tax, and
  fulfillment immediately before creating the PayPal order.

The storefront health response reports whether Channel3 is configured.

## AG Grid / AG Studio: retail merchant control center

The retail portal has an **Analytics** view backed by AG Studio. It exposes governed,
browser-local data sources for performance trends, catalog, inventory alerts, order issues,
recent orders, and change history. Operators can build grids, KPI tiles, charts, filters,
and cross-filtered reports without changing the agent backend.

Set `NEXT_PUBLIC_AG_STUDIO_LICENSE_KEY` for a licensed deployment. The sponsor package is
commercial software; the application remains usable without that variable according to the
package's trial behavior. Only merchant API responses are passed into Studio—no server keys
or payment credentials enter the dashboard.

## Bryntum: travel revenue schedule

The travel portal has a **Schedule** view using Bryntum Scheduler. Properties are resources;
weekly occupancy/rates are events; agent-staged overrides are orange. The scheduler is
read-only by design: pricing changes still go through the merchant agent's stage, preview,
AI auto-approval, and apply sequence.

The dependency uses Bryntum's npm trial alias for hackathon development. Replace it with the
licensed package source before production distribution.

## APIMatic: API contracts, SDKs, and documentation

Run `python scripts/export_openapi.py` to load each actual FastAPI app and produce its
OpenAPI contract in an APIMatic `src/spec` layout. See
[`integrations/apimatic/README.md`](../integrations/apimatic/README.md) for validation and
SDK commands. Generated SDKs are clients only; all authorization and commerce invariants
remain server-side.

## LLM through OpenRouter

`OPENROUTER_API_KEY` enables the model runtime, and the default model is
`deepseek/deepseek-v4.1-flash`. Override it with `OPENROUTER_MODEL`. The existing model
provider keeps its Anthropic-compatible fallback path, while model tool calls continue to
pass through the same tool schemas, provenance gates, spend caps, and approval controls.
