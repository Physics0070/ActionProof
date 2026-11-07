"""Shared helpers for gate tests: a wired Gate over the mocks, hero and JSON-export requests.

PDF claims (hero) run the real dual extraction; JSON-export claims are cheap, so loops use them.
"""
import hashlib
import json
import os
import sys
from pathlib import Path

from psycopg.types.json import Jsonb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "fixtures"))

import hero  # noqa: E402

from actionproof import db as dbmod  # noqa: E402
from actionproof.config import Settings  # noqa: E402
from actionproof.contracts import ActionRequest  # noqa: E402
from actionproof.gate import Gate, Principal  # noqa: E402

AGENT = Principal("agent-7", "user-123")  # the trusted session identity of the honest test agent


class KitGate(Gate):
    """Test-only: the transport's session identity is AGENT unless a test passes another `principal`.
    The real Gate has no default (ADR-012); tests that probe identity pass the principal explicitly."""

    def prepare(self, req, docs=None, *, principal=AGENT):
        return super().prepare(req, docs, principal=principal)

    def commit(self, receipt, req, review_token=None, *, principal=AGENT):
        return super().commit(receipt, req, review_token, principal=principal)
from actionproof.mocks import MockERP, MockPayments, MockRefunds  # noqa: E402
from actionproof.signing import Signer  # noqa: E402

HERO_DOCS = hero.load_docs()
INVOICE_TOOL, REFUND_TOOL = "payments.approve_invoice", "payments.refund_payment"


def rules(result) -> list[str]:
    return [r.rule for r in result.reasons]


def json_doc(**fields) -> bytes:
    return json.dumps(fields, sort_keys=True).encode()


def json_claim(doc_id: str, blob: bytes, key: str, value: str) -> dict:
    return {"value": value, "claim": "DIRECT", "src": {"doc": doc_id, "pointer": f"/{key}"},
            "doc_sha256": hashlib.sha256(blob).hexdigest()}


class _Pooled:
    """Test-only pooled connection: a new Postgres backend costs ~240 ms on Windows. close() and the context
    manager roll back / commit exactly like psycopg, then return the clean connection to the pool."""

    def __init__(self, pool: list, conn):
        object.__setattr__(self, "_pool", pool)
        object.__setattr__(self, "_c", conn)

    def __getattr__(self, name):
        return getattr(self._c, name)

    def __setattr__(self, name, value):
        setattr(self._c, name, value)

    def __enter__(self):
        return self

    def __exit__(self, et, ev, tb):
        if not self._c.closed:
            self._c.rollback() if et else self._c.commit()
        self.close()

    def close(self):
        c = self._c
        if c.closed:
            return
        try:
            c.rollback()
            c.isolation_level = None
        except Exception:
            c.close()
            return
        if len(self._pool) < 16:
            self._pool.append(c)
        else:
            c.close()


_POOLS: dict[str, list] = {}


def pooled_factory(url: str):
    pool = _POOLS.setdefault(url, [])

    def factory():
        try:
            conn = pool.pop()
        except IndexError:
            conn = dbmod.connect(url=url)
        return _Pooled(pool, conn)

    return factory


class Kit:
    def __init__(self, pg: str, opa_url: str, key_path, db):
        self.pg = pg
        self.db = db
        self.factory = pooled_factory(pg)
        self.erp = MockERP(self.factory)
        self.tool = MockPayments(self.erp, self.factory)
        self.refunds = MockRefunds(self.erp, self.factory)  # second connector (ADR-009), same gate
        self.settings = Settings(database_url=pg, opa_url=opa_url,
                                 tesseract_cmd=os.environ.get("TESSERACT_CMD", "tesseract"),
                                 signing_key_path=str(key_path))
        self.signer = Signer.from_path(self.settings.signing_key_path, self.settings.signing_kid)
        self.gate = KitGate(self.settings, self.signer, self.factory,
                            {INVOICE_TOOL: self.tool, REFUND_TOOL: self.refunds})
        # Count how often the GATE invoked execute, per tool (the mocks' .calls count tool-side effects).
        self.executes = 0
        self.refund_executes = 0

        def counter(tool, attr):
            real = tool.execute

            def counted(*a, **kw):
                setattr(self, attr, getattr(self, attr) + 1)
                return real(*a, **kw)

            tool.execute = counted

        counter(self.tool, "executes")
        counter(self.refunds, "refund_executes")

    # --- database helpers (autocommit-style on the kit's own connection)
    def sql(self, q: str, params=()):
        cur = self.db.execute(q, params)
        rows = cur.fetchall() if cur.description else None
        self.db.commit()
        return rows

    def version(self, record_id: str = "invoice:INV-2048") -> int:
        return self.sql("SELECT version FROM records WHERE record_id = %s", (record_id,))[0][0]

    def commits(self) -> int:
        return self.sql("SELECT count(*) FROM commits")[0][0]

    def seed_invoice(self, invoice_id: str, total: str, po_total: str, vendor: str = "V-ACME") -> None:
        po_id = f"PO-{invoice_id}"
        self.sql("INSERT INTO records (record_id, kind, data, version) VALUES (%s, 'invoice', %s, 1) "
                 "ON CONFLICT (record_id) DO UPDATE SET data = EXCLUDED.data, version = 1",
                 (f"invoice:{invoice_id}", Jsonb({"vendor_id": vendor, "total": total, "status": "open", "po_id": po_id})))
        self.sql("INSERT INTO records (record_id, kind, data, version) VALUES (%s, 'po', %s, 1) "
                 "ON CONFLICT (record_id) DO UPDATE SET data = EXCLUDED.data, version = 1",
                 (f"po:{po_id}", Jsonb({"vendor_id": vendor, "total": po_total})))

    def set_scope(self, max_amount: str, vendors=("V-ACME",), who: str = "user-123") -> None:
        self.sql("UPDATE delegations SET max_amount = %s::numeric, vendors = %s WHERE on_behalf_of = %s",
                 (max_amount, list(vendors), who))

    # --- requests
    def hero(self, idem: str = "idem-1") -> tuple[ActionRequest, dict]:
        return hero.hero_request(idem), HERO_DOCS

    def hero_allow(self, idem: str = "idem-allow") -> tuple[ActionRequest, dict]:
        """Hero invoice (4800.00) against a 4750.00 PO taken from the system of record: variance 50.00 -> ALLOW."""
        self.sql("UPDATE records SET data = data || '{\"total\": \"4750.00\"}'::jsonb WHERE record_id = 'po:PO-2048'")
        d = hero.hero_request(idem).model_dump(mode="json")
        del d["args"]["po.total"]
        d["args"]["variance"]["value"] = "50.00"
        return ActionRequest.model_validate(d), HERO_DOCS

    def json_request(self, invoice_id: str, total: str, po_total: str | None = None, *, idem: str | None = None,
                     variance: str | None = None, actor: str = "agent-7", seed: bool = True, **over):
        """An invoice export (JSON) request; seeds the matching invoice + PO records unless seed=False."""
        po_total = po_total or total
        if seed:
            self.seed_invoice(invoice_id, total, po_total)
        doc_id = f"export-{invoice_id}.json"
        blob = json_doc(invoice_id=invoice_id, total=total)
        from decimal import Decimal
        var = variance or str((Decimal(total) - Decimal(po_total)).quantize(Decimal("0.01")))
        d = {
            "tool": "payments.approve_invoice",
            "on_behalf_of": "user-123",
            "actor": actor,
            "idempotency_key": idem or f"idem-{invoice_id}",
            "args": {
                "invoice_id": json_claim(doc_id, blob, "invoice_id", invoice_id),
                "amount": json_claim(doc_id, blob, "total", total),
                "invoice.total": json_claim(doc_id, blob, "total", total),
                "variance": {"value": var, "claim": "DERIVED", "fn": "sub", "inputs": ["invoice.total", "po.total"]},
            },
        }
        d.update(over)
        try:
            return ActionRequest.model_validate(d), {doc_id: blob}
        except ValueError:  # e.g. a non-canonical actor: hand the raw dict to the gate, which must DENY it
            return d, {doc_id: blob}

    # --- refunds (ADR-009): the second connector through the same gate
    def seed_refunds(self) -> None:
        """PAY-7731 and the benign refund payments (db.PAYMENTS), plus user-123's refund customer scope."""
        dbmod.seed_refunds(self.db)

    def seed_payment(self, payment_id: str, customer: str, amount: str, method: str) -> None:
        self.sql("INSERT INTO records (record_id, kind, data, version) VALUES (%s, 'payment', %s, 1) "
                 "ON CONFLICT (record_id) DO UPDATE SET data = EXCLUDED.data, version = 1",
                 (f"payment:{payment_id}", Jsonb({"customer_id": customer, "amount": amount, "method_id": method,
                                                  "status": "captured"})))
        self.sql("UPDATE delegations SET customers = array_append(customers, %s) "
                 "WHERE on_behalf_of = 'user-123' AND NOT (%s = ANY(customers))", (customer, customer))

    def prior_refunds(self, customer: str, amounts, actor: str = "agent-7") -> None:
        """Refunds committed earlier for (actor, customer): rows in `commits`, counterparty in vendor_id (ADR-015)."""
        for i, amount in enumerate(amounts):
            self.sql("INSERT INTO commits (nonce, idempotency_key, request_hash, actor, on_behalf_of, vendor_id, "
                     "amount, record_id, created_at) VALUES (%s, %s, 'prior', %s, 'user-123', %s, %s, %s, 1)",
                     (f"prior-{actor}-{customer}-{i}", f"prior-{actor}-{customer}-{i}", actor, customer, amount,
                      f"payment:PRIOR-{customer}-{i}"))

    def refund(self, doc_id: str = "refund/REF-512.pdf", idem: str = "idem-ref", **kw) -> tuple[ActionRequest, dict]:
        return hero.refund_request(doc_id, idem, **kw), HERO_DOCS

    def refund_json(self, payment_id: str, amount: str, customer: str, method: str, *, idem: str,
                    **arg_over) -> tuple[ActionRequest, dict]:
        """A refund-request export (JSON) for a payment seeded with seed_payment; cheap, so loops use it."""
        doc_id = f"refund-{payment_id}-{idem}.json"
        blob = json_doc(payment_id=payment_id, amount=amount)
        args = {
            "payment_id": json_claim(doc_id, blob, "payment_id", payment_id),
            "customer_id": {"value": customer, "claim": "ASSERTED"},
            "refund_to": {"value": method, "claim": "ASSERTED"},
            "amount": json_claim(doc_id, blob, "amount", amount),
        }
        args.update(arg_over)
        d = {"tool": REFUND_TOOL, "on_behalf_of": "user-123", "actor": "agent-7", "idempotency_key": idem,
             "args": args}
        return ActionRequest.model_validate(d), {doc_id: blob}

    def mint(self, receipt: dict, req: ActionRequest, reviewer_login: str = "rev-alice") -> str:
        """The console's call: the reviewer is the session subject; rev-alice is a different person (ADR-008)."""
        return self.gate.mint_review_token(receipt, req, reviewer_login=reviewer_login)
