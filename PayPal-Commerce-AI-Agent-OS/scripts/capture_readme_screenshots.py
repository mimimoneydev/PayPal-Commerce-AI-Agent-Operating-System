# Copyright 2026 Anthropic PBC
# SPDX-License-Identifier: Apache-2.0

"""Capture the README screenshots from a *running* retail demo with Playwright.

These are photographs of the real application, not mockups: the storefront and merchant
portal are the shipped Next.js apps, the API serves the checked-in ACME fixture data, and
each generative card is the same component a live agent turn renders. The only frame with
placeholder identifiers is ``04-bounded-autobuy-receipt`` — it is the component showcase
fixture and says so on screen. No PayPal order, capture, webhook, or sandbox credential is
invented here; see SANDBOX-PROOF.md for the real-transaction record.

Start the demo first (offline mode is enough — no credentials needed for these frames):

    python scripts/run_demo.py retail --all --no-paypal
    pip install playwright && playwright install chromium        # one time
    python scripts/capture_readme_screenshots.py

Output defaults to ``docs/screenshots/``. Override with ``--out`` or the two ``--*-url``
options when the demo runs on different ports.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO_ROOT / "docs" / "screenshots"


def hide_dev_overlay(page: Page) -> None:
    """Remove Next.js's dev-only "Issues" badge; it is not part of the product UI."""
    page.evaluate("document.querySelectorAll('nextjs-portal').forEach(n => n.remove())")


def shot(page: Page, out: Path, name: str, selector: str | None = None) -> None:
    """Capture the whole viewport, or one generative card by its data-component name."""
    hide_dev_overlay(page)
    if selector:
        element = page.locator(selector).first
        element.scroll_into_view_if_needed()
        page.wait_for_timeout(400)
        hide_dev_overlay(page)
        element.screenshot(path=str(out / f"{name}.png"))
    else:
        page.screenshot(path=str(out / f"{name}.png"))
    print(f"captured docs/screenshots/{name}.png")


def visit(page: Page, url: str) -> None:
    page.goto(url, wait_until="networkidle")
    page.wait_for_timeout(1_000)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--storefront-url", default="http://localhost:3000")
    parser.add_argument("--merchant-url", default="http://localhost:3100")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    out: Path = args.out
    if not out.exists():
        out.mkdir(parents=True)

    base_store = args.storefront_url.rstrip("/")
    base_merchant = args.merchant_url.rstrip("/")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1480, "height": 940})

        visit(page, base_store)
        shot(page, out, "01-storefront-home")

        visit(page, f"{base_store}/showcase")
        shot(page, out, "02-product-cards", '[data-component="products"]')
        shot(page, out, "03-comparison", '[data-component="comparison"]')
        shot(page, out, "04-bounded-autobuy-receipt", '[data-component="checkout-receipt"]')
        shot(page, out, "05-cart", '[data-component="cart"]')

        visit(page, base_merchant)
        shot(page, out, "06-merchant-home")
        nav = page.locator('nav[aria-label="Portal views"]').first
        nav.get_by_role("button", name="Catalog").first.click()
        page.wait_for_timeout(1_000)
        shot(page, out, "07-merchant-catalog")

        visit(page, f"{base_merchant}/showcase")
        shot(page, out, "08-staged-change-approval", '[data-component="change_preview"]')

        browser.close()

    print(f"\nSaved 8 frames to {out}")
    print("Provenance: real running demo, ACME fixture data, no recorded PayPal transaction.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
