# PayPal Commerce AI Agent Operating System (AI Agent OS)

PayPal Commerce AI Agent OS is organized as a commerce operating layer rather than an agent
with unrestricted access to a store. The model owns conversation and tool selection. The
host owns identity, permissions, money, durable state, and audit records. Backends own
catalog, inventory, order, and pricing truth.

## Control and data planes

```text
customer and operator surfaces
              |
              v
identity, tenant, session, and policy control plane
              |
              v
shopping and merchant agent runtimes
              |
              v
typed tools -> provenance gates -> guardrails -> audit events
              |
       +------+-------------------+
       |                          |
commerce backends          payment orchestration
catalog/cart/orders        immutable quote + PayPal
analytics/inventory        approval + capture + webhook
```

The existing shopping and merchant cores are the agent kernel. `commerce_common` supplies
the execution, fencing, memory, presentation, and payment primitives shared by hosts. A
production host replaces the example session, memory, and payment stores with its durable
tenant-scoped services while keeping their interfaces and invariants.

## Non-negotiable boundaries

- A principal and tenant come from authentication, never from model tool arguments.
- A model cannot create or capture a payment. It can only render a checkout handoff whose
  opaque URL was authored by the host.
- A checkout is an immutable priced snapshot. Capture must match its PayPal order, amount,
  and currency.
- A merchant write is staged, guarded, audited, and approved before it reaches a live system.
- Third-party and business data is fenced before it reaches a model.
- Every asynchronous provider event is authenticated and processed idempotently.
- Secrets, funding sources, payer details, and raw credentials are absent from prompts,
  transcripts, memories, and payment records.

## Production services

| Service | Reference implementation | Production replacement |
|---|---|---|
| Session and transcript | `examples/demo_common/sessions.py` | Authenticated Redis or database store with tenant keys |
| Agent memory | in-memory and owner-only JSON stores | Encrypted, tenant-scoped database with retention jobs |
| Payment state | `SQLitePaymentStore`, `PostgresPaymentStore` | Backed-up shared PostgreSQL |
| Catalog and cart | vertical mock backends; WooCommerce and Shopify adapters | Tenant-selected `StorefrontBackend` |
| Operations | each vertical's merchant backend | `MerchantBackend` over analytics and operating systems |
| Events | in-process app-event queue | Durable event bus and outbox |
| Audit | tool events and provider records | Append-only tenant audit stream |

## Build-out sequence

1. Put authentication and tenant authorization ahead of every host and MCP route.
2. Implement the two backend interfaces over systems of record, including an atomic final
   pricing service for shipping, tax, discounts, inventory reservation, and expiry.
3. Move sessions, payment records, memory, and staged changes to durable tenant-scoped stores.
4. Supply a store-specific `OrderFinalizer` to the included durable outbox worker for custom
   PayPal checkout. The destination must deduplicate checkout ids. WooCommerce native checkout
   already creates its order; its adapter reads that order back instead of creating a second one.
5. Add refunds, disputes, shipment tracking, reconciliation, and a double-entry ledger as
   separate permissioned workflows.
6. Add rate limits, fraud and sanctions controls, observability, key rotation, backup/restore,
   deletion workflows, and operational runbooks.

The included PayPal slice completes payment approval and capture. The optional
[merchant control service](merchant-platform.md) adds tenant administration, durable shopper
sessions, manual fraud review, approved provider operations, and Shopify clearing journals.
These are explicit business workflows, not model behaviors; see the guide for supported
actions and remaining integration boundaries.
