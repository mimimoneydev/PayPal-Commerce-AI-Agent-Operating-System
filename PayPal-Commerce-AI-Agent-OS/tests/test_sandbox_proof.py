# Copyright 2026 PayPal Commerce AI Agent OS contributors
# SPDX-License-Identifier: Apache-2.0

"""The sandbox proof must never invent evidence.

These tests exercise ``scripts/demo_paypal_order.py`` offline: no network, no
PayPal credentials, no filesystem writes. They guard the property that judges
care about most — every id, event and screenshot in SANDBOX-PROOF.md comes from
something that actually happened, and anything missing says NOT RECORDED.
"""

from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "demo_paypal_order.py"


@pytest.fixture(scope="module")
def proof_script():
    spec = importlib.util.spec_from_file_location("demo_paypal_order_under_test", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeScreenshot:
    """A stand-in for a real file, so no tempfile/disk permission is needed."""

    def __init__(self, name: str, size: int = 1024, is_file: bool = True) -> None:
        self.name = name
        self._size = size
        self._is_file = is_file

    @property
    def suffix(self) -> str:
        return Path(self.name).suffix

    def is_file(self) -> bool:
        return self._is_file

    def stat(self) -> SimpleNamespace:
        return SimpleNamespace(st_size=self._size)

    def __lt__(self, other: FakeScreenshot) -> bool:
        return self.name < other.name


class FakeScreenshotDir:
    def __init__(self, entries: list[FakeScreenshot] | None, exists: bool = True) -> None:
        self._entries = entries
        self._exists = exists

    def exists(self) -> bool:
        return self._exists

    def iterdir(self):
        return iter(self._entries or [])


def empty_proof() -> dict:
    return {
        "generated_at": "2026-11-07T00:00:00+00:00",
        "api_base": None,
        "webhook_id": None,
        "spend_cap": None,
        "ceiling": None,
        "steps": [],
        "screenshots": [],
    }


def test_missing_values_are_marked_not_recorded(proof_script) -> None:
    rendered = proof_script.render_proof(empty_proof())
    assert "NOT RECORDED" in rendered
    assert "Webhook id configured:** no" in rendered
    assert "Sandbox verification item" not in rendered
    # No provider identifier may be synthesized for an empty run.
    assert "paypal_order_id=" not in rendered
    assert "capture_id=" not in rendered


def test_real_steps_keep_their_real_evidence(proof_script) -> None:
    proof = empty_proof()
    proof["api_base"] = "https://api-m.sandbox.paypal.com"
    proof["spend_cap"] = "25.00"
    proof["steps"] = [
        proof_script.step("create Orders v2 order", "RECORDED", paypal_order_id="REAL-ORDER-1"),
        proof_script.step("capture", "RECORDED", capture_id="REAL-CAPTURE-1"),
        proof_script.step("signed webhook", "NOT RECORDED", note="no real delivery received"),
    ]
    rendered = proof_script.render_proof(proof)
    assert "REAL-ORDER-1" in rendered
    assert "REAL-CAPTURE-1" in rendered
    assert "| signed webhook | NOT RECORDED |" in rendered
    assert "## Judge sandbox credentials" in rendered
    assert "action for the submitter" in rendered


def test_rendered_proof_never_contains_credentials(proof_script, monkeypatch) -> None:
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "DO-NOT-LEAK-SERVER-SECRET")
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "DO-NOT-LEAK-CLIENT-ID")
    rendered = proof_script.render_proof(empty_proof())
    assert "DO-NOT-LEAK" not in rendered


def test_screenshot_inventory_lists_only_real_images(proof_script, monkeypatch) -> None:
    monkeypatch.setattr(proof_script, "SCREENSHOTS_DIR", FakeScreenshotDir(None, exists=False))
    assert proof_script.screenshot_inventory() == []

    monkeypatch.setattr(
        proof_script,
        "SCREENSHOTS_DIR",
        FakeScreenshotDir(
            [
                FakeScreenshot("b-approval.png", 2048),
                FakeScreenshot("a-receipt.jpg", 4096),
                FakeScreenshot("notes.txt", 10),
                FakeScreenshot("not-a-file.webp", 1, is_file=False),
            ]
        ),
    )
    assert proof_script.screenshot_inventory() == [
        {"file": "proof/screenshots/a-receipt.jpg", "bytes": 4096},
        {"file": "proof/screenshots/b-approval.png", "bytes": 2048},
    ]


def test_no_screenshots_produces_capture_instructions(proof_script) -> None:
    rendered = proof_script.render_proof(empty_proof())
    assert "**NOT RECORDED.** No files in `proof/screenshots/`" in rendered
    assert "--proof-only" in rendered


def test_replay_events_without_a_capture_file_is_empty(proof_script) -> None:
    assert proof_script.replay_events(Path("/no-such-commerce-os-webhook.jsonl")) == []


def test_host_status_without_an_api_url_makes_no_request(proof_script) -> None:
    assert proof_script.host_status(None, "opaque-token") is None
    assert proof_script.host_status("", "opaque-token") is None


def test_unconfigured_check_writes_nothing(proof_script, monkeypatch, capsys) -> None:
    for key in ("PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET"):
        monkeypatch.delenv(key, raising=False)
    args = proof_script.build_parser().parse_args(
        ["--check", "--env-file", str(proof_script.REPO_ROOT / ".env.nonexistent")]
    )
    assert asyncio.run(proof_script.run(args)) == 2
    output = capsys.readouterr().out
    assert "MISSING PayPal sandbox credentials" in output
    assert "no identifiers were invented" in output


def test_proof_only_without_a_recorded_run_writes_nothing(
    proof_script, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        proof_script, "PROOF_JSON", proof_script.REPO_ROOT / "proof" / ".absent.json"
    )
    args = proof_script.build_parser().parse_args(["--proof-only"])
    assert asyncio.run(proof_script.run(args)) == 2
    assert "No recorded transaction yet" in capsys.readouterr().out


def test_live_environment_is_refused(proof_script, monkeypatch, capsys) -> None:
    """Sandbox only: a stray production credential must never start a real order."""
    monkeypatch.setenv("PAYPAL_CLIENT_ID", "fake-id")
    monkeypatch.setenv("PAYPAL_CLIENT_SECRET", "fake-secret")
    monkeypatch.setenv("PAYPAL_ENVIRONMENT", "live")
    args = proof_script.build_parser().parse_args(
        ["--check", "--env-file", str(proof_script.REPO_ROOT / ".env.nonexistent")]
    )
    assert asyncio.run(proof_script.run(args)) == 2
    assert "REFUSING" in capsys.readouterr().out
