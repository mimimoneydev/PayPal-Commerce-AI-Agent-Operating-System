# Copyright 2026 PayPal Commerce AI Agent OS contributors
# SPDX-License-Identifier: Apache-2.0

"""Host-action capabilities for the merchant approval surface.

A session id proves only that a caller started a portal session; it is not an
operator identity. Before the preview card may apply or discard a staged change,
the portal asks this gate for a short-lived, single-use capability bound to that
session, that change and that action. A bare ``POST /changes/{id}/apply`` carries
no capability and is refused, so the write cannot be driven by a scanner, a link,
or a cross-site form.

This is defence in depth, not authentication: a public demo still has no login.
A real deployment sets ``COMMERCE_MERCHANT_OPERATOR_TOKEN`` (or puts an
authenticating proxy in front and injects the operator header); see ``docs/safety.md``.
"""

from __future__ import annotations

import hmac
import os
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

APPROVAL_HEADER = "X-Merchant-Approval"
OPERATOR_TOKEN_HEADER = "X-Merchant-Operator-Token"
DEFAULT_TTL_SECONDS = 300


@dataclass(frozen=True)
class _Grant:
    session_id: str
    change_id: str
    action: str
    expires_at: float


class ApprovalGate:
    """Issues and consumes single-use capabilities for host approval actions.

    ``clock`` is injectable so a test can expire a capability without waiting.
    Grants live in process memory, like the demo's sessions; a real deployment
    would keep them beside its session store.
    """

    def __init__(
        self,
        *,
        operator_token: str | None = None,
        ttl: int = DEFAULT_TTL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._operator_token = operator_token
        self.ttl = ttl
        self._clock = clock
        self._grants: dict[str, _Grant] = {}
        self._lock = threading.Lock()

    @classmethod
    def from_env(cls) -> ApprovalGate:
        """The demo runs with no operator token; a deployment sets one to require it."""
        token = os.environ.get("COMMERCE_MERCHANT_OPERATOR_TOKEN", "").strip() or None
        return cls(operator_token=token)

    @property
    def requires_operator_token(self) -> bool:
        return self._operator_token is not None

    def operator_token_valid(self, supplied: str | None) -> bool:
        if self._operator_token is None:
            return True
        return bool(supplied) and hmac.compare_digest(supplied, self._operator_token)

    def issue(self, *, session_id: str, change_id: str, action: str) -> str:
        """A capability for exactly one session, change and action."""
        nonce = secrets.token_urlsafe(24)
        grant = _Grant(
            session_id=session_id,
            change_id=change_id,
            action=action,
            expires_at=self._clock() + self.ttl,
        )
        now = self._clock()
        with self._lock:
            # Grants are small and short-lived; prune on issue so the map cannot grow
            # with abandoned preview cards.
            expired = [key for key, value in self._grants.items() if value.expires_at < now]
            for key in expired:
                del self._grants[key]
            self._grants[nonce] = grant
        return nonce

    def consume(self, token: str | None, *, session_id: str, change_id: str, action: str) -> bool:
        """Spend a capability. It is removed on *any* attempt, valid or not, so a
        guessed or replayed token can never be retried."""
        if not token:
            return False
        with self._lock:
            grant = self._grants.pop(token, None)
        if grant is None:
            return False
        return (
            grant.expires_at >= self._clock()
            and hmac.compare_digest(grant.session_id, session_id)
            and hmac.compare_digest(grant.change_id, change_id)
            and hmac.compare_digest(grant.action, action)
        )
