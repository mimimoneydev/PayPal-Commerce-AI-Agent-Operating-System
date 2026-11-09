#!/usr/bin/env python3
# Copyright 2026 PayPal Commerce AI Agent OS contributors
# SPDX-License-Identifier: Apache-2.0

"""Record a REAL PayPal sandbox transaction and write SANDBOX-PROOF.md.

    python scripts/demo_paypal_order.py --check          # validate config, no network
    python scripts/demo_paypal_order.py                  # full sandbox run

Flow, all against api-m.sandbox.paypal.com:

    immutable cart snapshot -> create Orders v2 order -> buyer approves in a browser
    -> capture -> signed webhook reconciliation -> provider order status -> proof

This script NEVER invents an order id, capture id, webhook event, screenshot, or
credential. Every value in the generated proof comes from a live PayPal response or
from a file that actually exists on disk. Steps that did not happen are written as
"NOT RECORDED", not as successes.

Prerequisites (see SANDBOX-PROOF.md for the judge-ready checklist):
  * A PayPal REST app in SANDBOX mode; PAYPAL_CLIENT_ID and PAYPAL_CLIENT_SECRET.
  * A sandbox PERSONAL (buyer) account to approve the order in the browser.
  * Optional but recommended: PAYPAL_WEBHOOK_ID plus a public tunnel to this
    script's local webhook listener, so a genuinely signed event can be verified.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import threading
import time
import urllib.request
import webbrowser
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "commerce-common"))

PROOF_DIR = REPO_ROOT / "proof"
SCREENSHOTS_DIR = PROOF_DIR / "screenshots"
PROOF_MD = REPO_ROOT / "SANDBOX-PROOF.md"
PROOF_JSON = PROOF_DIR / "sandbox-transaction.json"


def load_environment(env_file: Path) -> None:
    """Root .env first, process environment wins; python-dotenv is optional."""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    if env_file.exists():
        load_dotenv(env_file, override=False)


class WebhookCollector:
    """A loopback-only receiver for genuinely PayPal-signed webhook deliveries.

    Point a public tunnel at --webhook-port and register the resulting HTTPS URL on
    the sandbox REST app. Nothing here is synthesized: the handler writes exactly the
    bytes and headers PayPal sent, and the caller verifies the signature with PayPal.
    """

    def __init__(self, path: Path, port: int) -> None:
        self.path = path
        self.port = port
        self.events: list[tuple[dict[str, str], dict[str, Any]]] = []
        self._lock = threading.Lock()
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        collector = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:  # noqa: N802 - stdlib signature
                length = int(self.headers.get("Content-Length", "0") or 0)
                raw = self.rfile.read(length)
                headers = {k.lower(): v for k, v in self.headers.items()}
                try:
                    event = json.loads(raw)
                except (ValueError, UnicodeDecodeError):
                    self.send_response(400)
                    self.end_headers()
                    return
                if isinstance(event, dict):
                    with collector._lock:
                        collector.events.append((headers, event))
                    collector.path.parent.mkdir(parents=True, exist_ok=True)
                    with collector.path.open("a", encoding="utf-8") as sink:
                        sink.write(json.dumps({"headers": headers, "event": event}) + "\n")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"ok":true}')

            def log_message(self, *_args: Any) -> None:
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def drain(self) -> list[tuple[dict[str, str], dict[str, Any]]]:
        with self._lock:
            events = list(self.events)
            self.events.clear()
        return events

    def close(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()


def replay_events(path: Path) -> list[tuple[dict[str, str], dict[str, Any]]]:
    """Real events captured earlier (JSONL of {"headers": ..., "event": ...})."""
    if not path.exists():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        record = json.loads(line)
        events.append((record["headers"], record["event"]))
    return events


def screenshot_inventory() -> list[dict[str, Any]]:
    """Only files that actually exist. Never generate or describe a fake screenshot."""
    if not SCREENSHOTS_DIR.exists():
        return []
    return [
        {"file": f"proof/screenshots/{p.name}", "bytes": p.stat().st_size}
        for p in sorted(SCREENSHOTS_DIR.iterdir())
        if p.is_file() and p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}
    ]


def step(name: str, status: str, **fields: Any) -> dict[str, Any]:
    return {"step": name, "status": status, **fields}


def render_proof(proof: dict[str, Any]) -> str:
    steps = proof["steps"]
    screenshots = proof["screenshots"]

    def line(label: str, value: Any) -> str:
        return f"- **{label}:** {value if value not in (None, '') else 'NOT RECORDED'}"

    rows = ["| Step | Status | Evidence |", "| --- | --- | --- |"]
    for s in steps:
        evidence = ", ".join(
            f"`{k}={v}`"
            for k, v in s.items()
            if k not in {"step", "status", "note"} and v not in (None, "")
        )
        rows.append(f"| {s['step']} | {s['status']} | {evidence or '—'} |")

    lines = [
        "# PayPal sandbox transaction proof",
        "",
        f"_Generated {proof['generated_at']} by `scripts/demo_paypal_order.py`._",
        "",
        "> This file is written only from live PayPal sandbox responses. It contains no",
        "> invented identifiers and no credentials. Sandbox only — no real money moves.",
        "",
        "## Environment",
        "",
        line("API base", proof.get("api_base")),
        line("Webhook id configured", "yes" if proof.get("webhook_id") else "no"),
        line("Spend cap", proof.get("spend_cap")),
        line("Host ceiling", proof.get("ceiling")),
        "",
        "## Recorded steps",
        "",
        *rows,
        "",
        "## Screenshots",
        "",
    ]
    if screenshots:
        lines += [f"- `{s['file']}` ({s['bytes']} bytes)" for s in screenshots]
    else:
        lines += [
            "**NOT RECORDED.** No files in `proof/screenshots/`. Capture these during the",
            "run, drop them in that directory, then re-run with `--proof-only` to refresh",
            "this file before publishing:",
            "",
            "1. The PayPal approval page showing the sandbox buyer and the amount.",
            "2. The hosted checkout page showing the authorized cap and PayPal order id.",
            "3. The captured state: provider status `COMPLETED` and the capture id.",
            "4. The chat turn where `create_paypal_order` is called behind the provenance gate.",
        ]

    lines += [
        "",
        "## Judge sandbox credentials",
        "",
        "**NOT RECORDED — this is an action for the submitter, not something a script can",
        "create.** PayPal credentials belong to a PayPal Developer account; generating or",
        "guessing them would be both impossible and a fabrication. Before submitting:",
        "",
        "1. In the [PayPal Developer Dashboard](https://developer.paypal.com/dashboard/),",
        "   create a dedicated sandbox **business** app for judges and a sandbox",
        "   **personal** buyer account. Copy the app's sandbox client id and secret.",
        "2. Put the sandbox client id / secret, `PAYPAL_ENVIRONMENT=sandbox`, the webhook",
        "   id, and the buyer account's email + password in the Devpost submission's",
        "   *Testing Instructions* field (or a password-protected gist linked there).",
        "   Never commit them to the repository.",
        "3. Add the HTTPS tunnel URL for this script's webhook listener to the app's",
        "   webhook subscriptions: `CHECKOUT.ORDER.APPROVED`, `PAYMENT.CAPTURE.COMPLETED`,",
        "   `PAYMENT.CAPTURE.DENIED`.",
        "4. Verify the buyer account has a sandbox balance before judging day.",
        "",
        "## Reproduce",
        "",
        "```bash",
        "cp .env.example .env   # fill PAYPAL_CLIENT_ID, PAYPAL_CLIENT_SECRET",
        "export PAYPAL_ENVIRONMENT=sandbox",
        "python scripts/demo_paypal_order.py --check",
        "python scripts/demo_paypal_order.py",
        "python scripts/run_demo.py retail   # PayPal is on by default",
        "```",
        "",
        "The machine-readable record is `proof/sandbox-transaction.json`.",
        "",
    ]
    return "\n".join(lines)


def write_proof(proof: dict[str, Any]) -> None:
    PROOF_DIR.mkdir(parents=True, exist_ok=True)
    SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
    PROOF_JSON.write_text(json.dumps(proof, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    PROOF_MD.write_text(render_proof(proof), encoding="utf-8")


def host_status(api_url: str | None, token: str) -> dict[str, Any] | None:
    """Exercise the host's order-status endpoint when the demo API is running."""
    if not api_url:
        return None
    url = f"{api_url.rstrip('/')}/api/payments/paypal/checkout/{token}/status"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return json.load(response)
    except Exception as error:  # the provider read above is the authoritative one
        return {"error": type(error).__name__}


async def run(args: argparse.Namespace) -> int:
    if args.proof_only:
        if not PROOF_JSON.exists():
            print("No recorded transaction yet; run the full script first.")
            return 2
        existing = json.loads(PROOF_JSON.read_text(encoding="utf-8"))
        existing["screenshots"] = screenshot_inventory()
        write_proof(existing)
        print(f"Refreshed {PROOF_MD.relative_to(REPO_ROOT)} from the recorded transaction.")
        return 0

    from commerce_common.payments import (
        CheckoutService,
        PaymentError,
        PaymentItem,
        PayPalClient,
        PayPalConfig,
        SQLitePaymentStore,
        money,
    )

    load_environment(args.env_file)
    missing = [
        k for k in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET") if not os.environ.get(k, "").strip()
    ]
    environment = os.environ.get("PAYPAL_ENVIRONMENT", "sandbox").strip().lower()
    proof: dict[str, Any] = {
        "generated_at": datetime.now(UTC).isoformat(),
        "api_base": None,
        "webhook_id": os.environ.get("PAYPAL_WEBHOOK_ID") or None,
        "spend_cap": None,
        "ceiling": None,
        "steps": [],
        "screenshots": screenshot_inventory(),
    }

    if missing:
        print("MISSING PayPal sandbox credentials: " + ", ".join(missing))
        print("Copy .env.example to .env and fill in the sandbox app's client id and secret.")
        print("Nothing was written; no identifiers were invented.")
        return 2
    if environment != "sandbox":
        print(
            "REFUSING: this script only runs against the PayPal sandbox (set PAYPAL_ENVIRONMENT=sandbox)."
        )
        return 2

    config = PayPalConfig.from_env()
    if config is None:  # defensive: from_env already handles the pair
        print("REFUSING: incomplete PayPal credentials.")
        return 2
    proof["api_base"] = config.base_url
    proof["webhook_id"] = config.webhook_id

    if args.check:
        print("PASS PayPal sandbox configuration")
        print(f"  api base       {config.base_url}")
        print(
            f"  webhook id     {'set' if config.webhook_id else 'NOT SET (webhook step will be skipped)'}"
        )
        print(f"  spend cap      {args.cap}")
        print(f"  host ceiling   {args.ceiling}")
        print("  no network calls were made; no transaction was recorded")
        return 0

    PROOF_DIR.mkdir(parents=True, exist_ok=True)
    collector = WebhookCollector(PROOF_DIR / "webhook-events.jsonl", args.webhook_port)
    client = PayPalClient(config)
    service = CheckoutService(
        SQLitePaymentStore(PROOF_DIR / "payments.sqlite3"),
        client,
        merchant_id="sandbox-proof",
        max_order_amount=args.ceiling,
    )
    cap = money(min(money(args.cap), money(args.ceiling)))
    proof["spend_cap"] = str(cap)
    proof["ceiling"] = str(money(args.ceiling))

    if not args.no_webhook_listener:
        try:
            collector.start()
            print(
                f"Webhook listener on 127.0.0.1:{args.webhook_port}. Register a public tunnel "
                "URL on the sandbox app to receive genuinely signed events."
            )
        except OSError as error:
            print(f"Webhook listener could not start ({error}); continuing without live events.")

    token = ""
    order_id = ""
    try:
        draft, token = await service.create_checkout(
            session_id="sandbox-proof-session",
            user_id="sandbox-proof-buyer",
            currency=args.currency,
            items=[
                PaymentItem(
                    product_id="SANDBOX-PROOF-1",
                    name="Sandbox verification item",
                    unit_amount=money(args.amount),
                    quantity=1,
                )
            ],
            spend_cap=cap,
        )
        proof["steps"].append(
            step(
                "immutable snapshot",
                "RECORDED",
                checkout_id=draft.checkout_id,
                cart_hash=draft.cart_hash,
                amount=str(draft.amount),
                currency=draft.currency,
                spend_cap=str(draft.spend_cap),
            )
        )
        created = await service.create_order(token)
        order_id = created.paypal_order_id or ""
        proof["steps"].append(
            step(
                "create Orders v2 order",
                "RECORDED",
                paypal_order_id=order_id,
                status=created.status,
                approval_url=created.approval_url,
            )
        )
        print(f"\nPayPal order created: {order_id}")
        if created.approval_url:
            print(f"Approve it here: {created.approval_url}")
            if not args.no_browser:
                webbrowser.open(created.approval_url)
        else:
            print("PayPal returned no approval URL; the proof will stop here.")
            return 1

        print("Waiting for buyer approval in the sandbox buyer account…")
        deadline = time.monotonic() + args.wait_seconds
        approved = False
        while time.monotonic() < deadline:
            current = await client.get_order(order_id)
            if current.status in {"APPROVED", "COMPLETED"}:
                approved = True
                proof["steps"].append(
                    step(
                        "buyer approval",
                        "RECORDED",
                        paypal_order_id=order_id,
                        status=current.status,
                    )
                )
                break
            await asyncio.sleep(3)
        if not approved:
            proof["steps"].append(
                step("buyer approval", "NOT RECORDED", note="timed out waiting for buyer approval")
            )
            print("Buyer approval did not arrive in time. Writing an honest partial proof.")
            return 1

        captured = await service.capture(token, order_id)
        proof["steps"].append(
            step(
                "capture",
                "RECORDED",
                paypal_order_id=order_id,
                capture_id=captured.capture_id,
                status=captured.status,
                amount=str(captured.amount),
                currency=captured.currency,
            )
        )
        print(f"Captured: {captured.capture_id}")

        provider = await client.get_order(order_id)
        proof["steps"].append(
            step(
                "provider order status",
                "RECORDED",
                paypal_order_id=provider.order_id,
                status=provider.status,
                capture_id=provider.capture_id,
            )
        )
        local = host_status(args.api_url, token)
        if local is not None:
            proof["steps"].append(
                step(
                    "host order status",
                    "RECORDED" if "error" not in local else "NOT RECORDED",
                    checkout_id=captured.checkout_id,
                    **(
                        {"error": local["error"]}
                        if "error" in local
                        else {
                            "status": local.get("status"),
                            "order_id": local.get("order_id"),
                        }
                    ),
                )
            )

        # Wait briefly for a real, signed webhook delivery, then verify with PayPal.
        events = collector.drain()
        if not events and args.webhook_wait > 0:
            wait_until = time.monotonic() + args.webhook_wait
            while time.monotonic() < wait_until and not events:
                await asyncio.sleep(1)
                events = collector.drain()
        events += replay_events(Path(args.webhook_event)) if args.webhook_event else []
        if not config.webhook_id:
            proof["steps"].append(
                step("signed webhook", "NOT RECORDED", note="PAYPAL_WEBHOOK_ID is not set")
            )
        elif not events:
            proof["steps"].append(
                step("signed webhook", "NOT RECORDED", note="no real delivery was received")
            )
        else:
            for headers, event in events:
                try:
                    processed, _ = await service.process_webhook(headers, event)
                    proof["steps"].append(
                        step(
                            "signed webhook",
                            "RECORDED" if processed else "NOT RECORDED",
                            event_id=event.get("id"),
                            event_type=event.get("event_type"),
                            processed=processed,
                        )
                    )
                except PaymentError as error:
                    proof["steps"].append(
                        step(
                            "signed webhook",
                            "NOT RECORDED",
                            event_id=event.get("id"),
                            event_type=event.get("event_type"),
                            note=str(error),
                        )
                    )
        return 0
    except PaymentError as error:
        proof["steps"].append(step("run", "FAILED", note=str(error)))
        print(f"PayPal sandbox step failed: {error}")
        return 1
    finally:
        collector.close()
        await client.aclose()
        proof["screenshots"] = screenshot_inventory()
        write_proof(proof)
        print(f"Wrote {PROOF_MD.relative_to(REPO_ROOT)} and {PROOF_JSON.relative_to(REPO_ROOT)}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--check", action="store_true", help="validate config, make no network calls"
    )
    parser.add_argument(
        "--proof-only",
        action="store_true",
        help="regenerate SANDBOX-PROOF.md from the recorded JSON (no network, no new transaction)",
    )
    parser.add_argument("--env-file", type=Path, default=REPO_ROOT / ".env")
    parser.add_argument("--amount", default="10.00", help="unit amount of the one-item proof cart")
    parser.add_argument("--currency", default="USD")
    parser.add_argument("--cap", default="25.00", help="shopper-authorized spend cap")
    parser.add_argument("--ceiling", default="250.00", help="server-side hard spend ceiling")
    parser.add_argument("--wait-seconds", type=int, default=300, help="buyer approval timeout")
    parser.add_argument("--webhook-port", type=int, default=8765)
    parser.add_argument(
        "--webhook-wait", type=int, default=20, help="seconds to wait for a signed event"
    )
    parser.add_argument(
        "--webhook-event", type=str, default="", help="JSONL of real captured events"
    )
    parser.add_argument("--no-webhook-listener", action="store_true")
    parser.add_argument("--no-browser", action="store_true", help="print the approval URL only")
    parser.add_argument("--api-url", default=os.environ.get("COMMERCE_PUBLIC_API_URL", ""))
    return parser


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run(build_parser().parse_args())))
