# PayPal AI Hackathon — submission copy

> **Draft for the submitter. Do not paste until the checklist at the bottom is complete.**
>
> Every `{{PLACEHOLDER}}` below must be replaced with a real value. Nothing in this file
> invents an order id, a capture id, a sandbox credential, a video URL, a deployed URL, or a
> usage metric. Where evidence does not exist yet, the text says so or omits the claim.

---

## 1. Title

```
PayPal Commerce AI Agent OS — bounded, provable agentic checkout
```

## 2. One-line summary

```
An AI shopping agent that can actually complete a PayPal sandbox purchase — but never above
the cap the shopper set, and never with a payment credential in the model's context.
```

## 3. Text description (paste into the Devpost description field)

AI shopping assistants are good at recommending products and bad at finishing the job. The
moment an agent is allowed to spend money, two questions appear at once: can it prove it only
bought what the customer asked for, and can it prove it stayed inside the amount the customer
authorized? Handing a language model a payment credential answers neither.

**PayPal Commerce AI Agent OS** is an open-source commerce operating system that puts PayPal
*inside* the agent loop rather than behind a checkout link. Its shopping agent searches,
compares, plans, fills a cart and — when a customer names both the items and a maximum total —
calls a built-in `create_paypal_order` tool that prepares a real PayPal Orders v2 order. That
tool is registered in the tool registry, both agent runtimes, and the storefront MCP server,
so PayPal is a first-class agent capability, not an optional bolt-on.

The design deliberately keeps the model away from money. The model supplies **only**
`product_ids` and `max_amount`. The host re-reads its own catalog for prices, quantities and
currency; freezes an immutable, hashed cart snapshot; and calls PayPal with credentials that
never enter model context. Three independent limits apply: the tool clamps the model-supplied
cap to a fixed maximum, the checkout service clamps it again to a deployment ceiling set by
`COMMERCE_MAX_ORDER_AMOUNT`, and an over-cap cart is refused *before any payment row is
written*. Every `product_id` must also have come from a catalog or order tool in that same
session — a provenance gate that stops the model from inventing products.

The result is a visible receipt: the authorized cap, the cart snapshot hash, and the PayPal
order id appear on both the hosted checkout page and the in-chat checkout card. The agent
**creates** an order; it never captures one. The customer approves on PayPal's page and the
host captures, verifies webhook signatures, deduplicates events, and reconciles status. The
hosted checkout page uses PayPal's JavaScript SDK; the server uses Orders v2 with OAuth,
`PayPal-Request-Id` idempotency, amount/currency equality checks, and a durable SQLite or
PostgreSQL payment store with a transactional order-finalization outbox. Lost capture
responses and delayed approval events are handled without issuing a second charge.

PayPal is on by default: `scripts/run_demo.py` enables sandbox checkout whenever credentials
are present, prints a loud warning when they are missing, and offers `--no-paypal` as the
explicit offline mode. `scripts/demo_paypal_order.py` executes the full
`create → buyer approve → capture → signed webhook → provider order status` path against
`api-m.sandbox.paypal.com`; it refuses live mode and writes proof only from real responses.
Its checked-in report is `SANDBOX-PROOF.md`.

The rest of the OS is a coherent, runnable product rather than a single script: a shopping
agent and a governed merchant agent, each defined once as prompt + skills + tool contracts +
gates and run through three compatible runtimes (Messages API, Agent SDK, Managed Agents);
four vertical demo applications (retail, travel, telecom, entertainment) across eight Next.js
apps; a plugin that scaffolds a new commerce agent; and a safety layer covering fencing,
provenance, memory validation, and staged human approval for every merchant write. The LLM
runs through OpenRouter (`deepseek/deepseek-v4.1-flash` by default). Sponsor integrations
include Channel3 retail discovery, AG Grid analytics in the merchant control center, a Bryntum
travel occupancy scheduler, and APIMatic-ready OpenAPI exports. The suite has 98 test files;
`pytest` and `python scripts/check.py` validate the tool registries, prompts, manifests and
documentation together.

**What is genuinely new in this submission period (1 Oct – 12 Nov 2026):** the PayPal Orders
v2 payment layer, the `create_paypal_order` agent tool and its provenance/cap gates, bounded
auto-buy with a visible receipt, default-on sandbox checkout, the sandbox proof harness,
commerce-platform adapters (WooCommerce, Shopify), the OpenRouter model runtime, the sponsor
integrations, and the architecture diagram — 64 new files plus substantial changes to existing
ones, recorded in `CHANGES.md`. The project builds on a third-party Apache-2.0-licensed
commerce-agent blueprint; it complies with that license (root `LICENSE`, `NOTICE`,
`CREDITS.md`, retained source notices) and materially enhances the underlying functionality
as the hackathon's open-source reuse rule requires.

The repository README includes eight real screenshots of the running retail demo — storefront,
fenced product cards, grounded comparison, the cap receipt card, cart, merchant workspace,
catalog and staged-change approval — with capture provenance and a script to regenerate them.
The receipt frame is explicitly labelled a component fixture; it is not presented as a
transaction.

**Scope honesty:** the verticals use fictional ACME catalogs and fixture data. This is a
developer platform and demo, not a live merchant deployment. No real customer, real revenue,
or production transaction is claimed.

## 4. Optional insert — add after a real sandbox run

> Only paste this paragraph after `scripts/demo_paypal_order.py` has completed against a real
> sandbox app and `SANDBOX-PROOF.md` has been regenerated with genuine values.

```
A complete sandbox transaction is recorded in SANDBOX-PROOF.md: PayPal order {{ORDER_ID}},
capture {{CAPTURE_ID}}, provider status COMPLETED, and the signed webhook event {{EVENT_ID}},
with screenshots of the approval page, the cap receipt, and the captured state in
proof/screenshots/.
```

## 5. Tools and technologies (paste into the tools/technologies field)

```
PayPal Orders v2 REST API, PayPal JavaScript SDK, PayPal Webhooks (signature verification),
PayPal sandbox, PayPal Partner Referrals; OpenRouter / deepseek-v4.1-flash; Python 3.11+,
FastAPI, Pydantic, SQLite, PostgreSQL/SQLAlchemy, httpx; Model Context Protocol (mcp 1.29.0);
Next.js / TypeScript / React / Tailwind; pytest, Ruff; Channel3, AG Grid, Bryntum, APIMatic.
```

## 6. Testing instructions (paste into the Devpost testing instructions field)

### 6.1 Judge credentials — provide these in this field, never in the repository

| Item | Value |
|---|---|
| Sandbox REST app client id | `{{PAYPAL_SANDBOX_CLIENT_ID}}` |
| Sandbox REST app secret | `{{PAYPAL_SANDBOX_CLIENT_SECRET}}` |
| Sandbox **personal / buyer** account email | `{{BUYER_EMAIL}}` |
| Sandbox **personal / buyer** account password | `{{BUYER_PASSWORD}}` |
| OpenRouter API key (for chat turns) | `{{OPENROUTER_API_KEY}}` |
| Webhook id, if a signed-event demo is provided | `{{PAYPAL_WEBHOOK_ID}}` |
| Hosted demo URL, if deployed | `{{DEMO_URL}}` |

Create these in the [PayPal Developer Dashboard](https://developer.paypal.com/dashboard/):
one sandbox **business** app for the server credentials, one sandbox **personal** account for
buyer approval, and a balance on the buyer account. All values must be sandbox-only. The
repository contains no credentials.

### 6.2 Prerequisites

Python 3.11+, Node 22, npm, git. A PayPal developer account and an OpenRouter key.

### 6.3 Install and run

```bash
git clone {{PUBLIC_REPO_URL}}
cd {{REPO_DIR}}
cd PayPal-Commerce-AI-Agent-OS
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
(cd examples && npm ci)
cp .env.example .env
```

Fill `.env` with the values from section 6.1:

```text
OPENROUTER_API_KEY=...
PAYPAL_CLIENT_ID=...
PAYPAL_CLIENT_SECRET=...
PAYPAL_ENVIRONMENT=sandbox
PAYPAL_WEBHOOK_ID=...
COMMERCE_MAX_ORDER_AMOUNT=250.00
```

Then start the retail demo (API on :8000, storefront on :3000):

```bash
python scripts/run_demo.py retail
```

`--all` also starts the merchant portal on :3100; `--merchant` starts only the portal;
`--no-paypal` runs the same UI in explicit offline mode with no PayPal routes. Browsing the
catalog, the product pages, and the portal widgets needs no credentials at all.

### 6.4 What to test, in order

1. **Ordinary agent loop.** Open `http://localhost:3000` and say:
   *"I'm taking my partner and our 6-year-old camping for the first time next month. We need
   a tent — nothing too heavy to deal with, ideally under $250."*
   Then: *"Compare the top two options for me — mostly care about space and ease of setup."*
   Expect fenced product cards, a grounded comparison, and an add-to-cart action.

2. **Bounded auto-buy (the PayPal-in-the-loop feature).** In a fresh session, first let a
   catalog tool return a product, then say:
   *"Buy that tent for me, but do not spend more than $200 total."*
   Expect the agent to call `create_paypal_order` and return a checkout card showing a PayPal
   order id, the authorized cap, the immutable cart snapshot hash, and an approval link.
   Confirm the model text contains **no** bearer checkout URL and that the card says nothing
   has been charged yet.

3. **Cap enforcement.** Repeat with a cap below the server-priced cart total. Expect
   `SpendCapExceeded`: the order is refused *before* any payment row or PayPal order exists.
   Also verify the ceiling: set `COMMERCE_MAX_ORDER_AMOUNT=5.00`, restart, and confirm a
   larger cart is refused even when the shopper names a larger cap.

4. **Provenance gate.** Ask the agent to buy a made-up product id that no catalog tool
   returned this session. Expect a refusal, not an order.

5. **Buyer approval and capture.** Open the approval link, log in with the sandbox **buyer**
   account from section 6.1, approve, and return to the hosted checkout page. Expect the
   receipt to show `COMPLETED`, the capture id, and the same cart hash. The host captures;
   the agent never does.

6. **Webhook reconciliation.** With `PAYPAL_WEBHOOK_ID` set and a public tunnel registered
   for `CHECKOUT.ORDER.APPROVED`, `PAYMENT.CAPTURE.COMPLETED`, `PAYMENT.CAPTURE.DENIED`,
   expect a genuinely signed event to be verified through
   `/v1/notifications/verify-webhook-signature` and deduplicated by event id.

7. **Full reproducible proof.** `python scripts/demo_paypal_order.py --check` (config only,
   no network), then `python scripts/demo_paypal_order.py` (opens the approval URL, waits for
   the buyer, captures, reads provider status, verifies the webhook, and writes
   `proof/sandbox-transaction.json` + `SANDBOX-PROOF.md`). This script refuses
   `PAYPAL_ENVIRONMENT=live` and never fabricates identifiers.

8. **Merchant agent and approval gate.** `python scripts/run_demo.py retail --all`, open
   `http://localhost:3100`, and ask *"What needs my attention this morning?"* followed by a
   restock request. Expect a staged change preview that does nothing until a person clicks
   Approve on the card.

9. **Automated checks.**

   ```bash
   pip install -r requirements-dev.txt
   ruff check . && pytest && python scripts/check.py
   python scripts/verify_all.py
   ```

### 6.5 Troubleshooting

- Missing PayPal credentials produce a loud startup warning; the UI still runs in offline
  mode. Use `python scripts/run_demo.py retail --no-paypal` to make that explicit.
- Chat needs `OPENROUTER_API_KEY`; `python3 scripts/test_openrouter.py` checks connectivity
  and tool calling without the UI.
- `--no-paypal` sets `COMMERCE_PAYPAL_DISABLED=1` and clears the credentials for the API
  process. `enable_agentic_payments=False` removes the agent's PayPal tool.
- Ports are preferences: a busy port moves the server to the next free one.

## 7. Submission URLs

| Field | Value |
|---|---|
| Public code repository | `{{PUBLIC_REPO_URL}}` |
| Demo video (public YouTube, < 3 min) | `{{YOUTUBE_URL}}` |
| Hosted demo (optional — setup instructions above also satisfy access) | `{{DEMO_URL}}` |
| Gallery images (upload from the repo, no upload URL needed) | `PayPal-Commerce-AI-Agent-OS/docs/screenshots/01-storefront-home.png`, `04-bounded-autobuy-receipt.png`, `06-merchant-home.png`, `08-staged-change-approval.png` |

## 8. Before you submit — checklist

- [ ] Create/restore the public GitHub repo and push all local changes; confirm the `LICENSE`
      is detected in the repository's **About** section. Only **one** commit exists locally
      and ~80 files are still uncommitted — this is the highest-priority blocker.
- [ ] Replace every `{{PLACEHOLDER}}` above; put judge credentials in the Devpost testing
      instructions field, never in the repo.
- [ ] README screenshots are already present in `PayPal-Commerce-AI-Agent-OS/docs/screenshots/`
      and are labelled honestly. Still to do: run one real sandbox transaction, regenerate
      `SANDBOX-PROOF.md`, capture approval / receipt / captured-state screenshots into
      `proof/screenshots/`, then paste the optional paragraph in section 4.
- [ ] Record and publish the < 3 minute YouTube video showing the bounded auto-buy end to
      end. No third-party trademarks or copyrighted music.
- [ ] Verify the project "functions as depicted in the video" — the rules require it.
- [ ] All materials in English. Add the sponsor prize categories being entered, if any.
- [ ] Note the prize cap rule: one Grand Prize + one Sponsor Prize, **or** one Honorable
      Mention + one Sponsor Prize.
