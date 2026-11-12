# README screenshots — provenance

These are real screenshots of the running application, not mockups. They were captured on
7 November 2026 with Playwright Chromium at a 1480 × 940 viewport from:

```bash
python scripts/run_demo.py retail --all --no-paypal
python scripts/capture_readme_screenshots.py
```

The API serves the checked-in ACME fixture data, and the generative cards are the same
components a live agent turn renders (the `/showcase` routes render them from
`lib/showcase-fixtures.ts` without needing a model key). The Next.js development overlay is
removed before capture; no product content is edited, staged, or composited.

**Honesty notes.** The run used `--no-paypal` because no sandbox credentials are present, so
no PayPal order, capture, or webhook was created. The data is fictional ACME catalog and
order data. Frame `04-bounded-autobuy-receipt` is the component showcase fixture and says so
on screen: its identifiers are deliberate placeholders (`FIXTURE-NOT-A-REAL-ORDER`), not
real PayPal order ids. Evidence of an actual transaction belongs only in
[`SANDBOX-PROOF.md`](../../SANDBOX-PROOF.md), written by
[`scripts/demo_paypal_order.py`](../../scripts/demo_paypal_order.py) from live sandbox
responses.

| Frame | What it shows |
|---|---|
| `01-storefront-home.png` | Shopping assistant home, order awareness, generative product shelf |
| `02-product-cards.png` | Fenced, provenance-checked product carousel |
| `03-comparison.png` | Grounded side-by-side comparison |
| `04-bounded-autobuy-receipt.png` | Cap receipt component: authorized cap, snapshot total, hash, order id placeholder |
| `05-cart.png` | Cart panel |
| `06-merchant-home.png` | Merchant workspace: KPIs, alerts, assistant rail |
| `07-merchant-catalog.png` | Governed catalog view with stock and content alerts |
| `08-staged-change-approval.png` | A merchant change preview card (shown in human-approval mode; AI auto-approval is the demo default) |

To regenerate after changing the UI, start the demo and rerun the capture script. To replace
frame 04 with a genuine transaction receipt, run one real sandbox purchase and capture the
hosted checkout page during that run.
