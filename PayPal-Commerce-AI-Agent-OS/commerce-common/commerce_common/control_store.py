"""Tenant-scoped durable control records, encrypted credentials, and CAS updates.

SQLite is useful locally; PostgreSQL uses exactly the same schema and transaction code.
No connection credentials or passwords are returned by the public projections.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time

from cryptography.fernet import Fernet
from sqlalchemy import Column, Integer, MetaData, String, Table, Text, and_, create_engine, select
from sqlalchemy.exc import IntegrityError


class Conflict(RuntimeError):
    pass


class ControlStore:
    def __init__(self, url: str, encryption_key: str):
        self.cipher = Fernet(encryption_key.encode())
        self.engine = create_engine(
            url,
            pool_pre_ping=True,
            connect_args={"check_same_thread": False, "timeout": 30}
            if url.startswith("sqlite")
            else {},
        )
        metadata = MetaData()
        self.records = Table(
            "commerce_control",
            metadata,
            Column("tenant", String(100), primary_key=True),
            Column("kind", String(40), primary_key=True),
            Column("key", String(256), primary_key=True),
            Column("version", Integer, nullable=False),
            Column("document", Text, nullable=False),
        )
        metadata.create_all(self.engine)

    def _where(self, tenant, kind, key):
        t = self.records.c
        return and_(t.tenant == tenant, t.kind == kind, t.key == key)

    def get(self, tenant, kind, key):
        with self.engine.connect() as db:
            row = (
                db.execute(select(self.records).where(self._where(tenant, kind, key)))
                .mappings()
                .first()
            )
        if not row:
            return None
        return {"key": row["key"], "version": row["version"], "data": json.loads(row["document"])}

    def put(self, tenant, kind, key, data, *, version=0):
        document = json.dumps(data, separators=(",", ":"), sort_keys=True)
        try:
            with self.engine.begin() as db:
                if version == 0:
                    db.execute(
                        self.records.insert().values(
                            tenant=tenant, kind=kind, key=key, version=1, document=document
                        )
                    )
                else:
                    result = db.execute(
                        self.records.update()
                        .where(self._where(tenant, kind, key), self.records.c.version == version)
                        .values(version=version + 1, document=document)
                    )
                    if result.rowcount != 1:
                        raise Conflict("Record changed; reload and retry")
        except IntegrityError as error:
            raise Conflict("Record already exists") from error
        return {"key": key, "version": version + 1, "data": data}

    def list(self, tenant, kind):
        with self.engine.connect() as db:
            rows = (
                db.execute(
                    select(self.records)
                    .where(self.records.c.tenant == tenant, self.records.c.kind == kind)
                    .order_by(self.records.c.key)
                )
                .mappings()
                .all()
            )
        return [
            {"key": r["key"], "version": r["version"], "data": json.loads(r["document"])}
            for r in rows
        ]

    def delete(self, tenant, kind, key):
        with self.engine.begin() as db:
            db.execute(self.records.delete().where(self._where(tenant, kind, key)))

    def save_secret(self, tenant, name, value):
        old = self.get(tenant, "secrets", name)
        encrypted = self.cipher.encrypt(json.dumps(value).encode()).decode()
        return self.put(
            tenant, "secrets", name, {"encrypted": encrypted}, version=old["version"] if old else 0
        )

    def secret(self, tenant, name):
        row = self.get(tenant, "secrets", name)
        return json.loads(self.cipher.decrypt(row["data"]["encrypted"].encode())) if row else None

    def audit(self, tenant, actor, action, subject):
        self.put(
            tenant,
            "audit",
            f"{time.time_ns()}-{secrets.token_hex(6)}",
            {
                "at": int(time.time()),
                "actor": actor,
                "action": action,
                "subject": subject,
            },
        )

    def require_member(self, tenant, user_id, *, owner=False):
        row = self.get(tenant, "members", user_id)
        if not row or (owner and row["data"]["role"] != "owner"):
            raise PermissionError("Merchant access denied")
        return row["data"]

    def ledger(self, tenant, event_id, currency, entries, *, description):
        # Integer minor units only. One atomic document is a balanced journal entry;
        # the unique event key deduplicates provider redelivery and accounting exports.
        if not entries or any(type(e.get("amount")) is not int for e in entries):
            raise ValueError("Ledger amounts must be integer minor units")
        if sum(e["amount"] for e in entries) != 0:
            raise ValueError("Journal is not balanced")
        data = {"currency": currency, "entries": entries, "description": description}
        old = self.get(tenant, "ledger", event_id)
        if old:
            if old["data"] != data:
                raise Conflict("Journal event cannot be rewritten")
            return old
        return self.put(tenant, "ledger", event_id, data)


def password_hash(password: str, salt: str | None = None):
    salt = salt or secrets.token_hex(16)
    value = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return salt + ":" + value


def password_matches(password: str, encoded: str):
    return hmac.compare_digest(password_hash(password, encoded.split(":")[0]), encoded)


def digest(value: str):
    return hashlib.sha256(value.encode()).hexdigest()
