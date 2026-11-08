"""Phase 6 task 1: the eval case format, the public catalog and the benign / handwritten corpora.

Static checks need no services. The last section is the only gate run: 10 attacks and 10 benign cases through the REAL
gate with a throwaway executor, to prove the format is executable and its expectations are right.
"""
import copy
import json
import re
import sys
import time
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "scripts"):
    sys.path.insert(0, str(p))

import gen_catalog  # noqa: E402

from eval import build_handwritten, gen_benign  # noqa: E402
from eval import cases as ev  # noqa: E402

CASES = ev.load_cases()


# ------------------------------------------------------------------ static
def test_all_committed_cases_validate_and_ids_are_unique():
    ids = Counter(c.id for c in CASES)
    assert [i for i, n in ids.items() if n > 1] == []


def test_counts_meet_the_minimums():
    s = ev.summarize(CASES)
    assert s["kind"]["benign"] >= 110
    assert s["origin"]["handwritten"] >= 70
    assert set(s["handwritten_class"]) == set(ev.CLASSES)
    assert all(s["handwritten_class"][c] >= 8 for c in ev.CLASSES), s["handwritten_class"]


def test_second_handwritten_set_counts_and_is_distinct_from_the_first():
    """handwritten2 is a second handwritten set, NOT independent of the gate (disclosed in docs/EVAL.md)."""
    hw2 = [c for c in CASES if c.set_name == "handwritten2"]
    assert len(hw2) >= 105
    per = Counter(c.class_ for c in hw2)
    assert set(per) == set(ev.CLASSES) and all(per[k] >= 15 for k in ev.CLASSES), per
    assert all(c.kind == "attack" and c.origin == "handwritten" and c.id.startswith("hw2-") for c in hw2)
    first = {c.id for c in CASES if c.set_name == "handwritten"}
    assert first and not first & {c.id for c in hw2}
    assert len({c.id for c in CASES}) == len(CASES)


def test_every_document_and_citation_resolves_against_the_catalog():
    manifest = ev.load_manifest()
    for c in CASES:
        for d in c.setup.documents:
            assert (d.derive_from or d.name) in manifest, (c.id, d.name)
        blobs, entries = ev.materialize_docs(c.setup, manifest)
        for s in c.steps:
            for st in (s.steps if s.op == "concurrent" else [s]):
                if st.op == "prepare":
                    wire = ev.resolve_request(st.request, c.principal, entries)
                    assert wire["args"], (c.id, st.id)


def test_derived_documents_have_their_own_hash():
    c = next(x for x in CASES if x.id == "atk-evi-self-made-po")
    blobs, entries = ev.materialize_docs(c.setup)
    assert entries["forged-po.pdf"]["sha256"] != entries["po.pdf"]["sha256"]
    assert blobs["forged-po.pdf"] != blobs["po.pdf"]


def test_benign_and_handwritten_files_are_exactly_what_their_generators_emit():
    for case in gen_benign.build():
        assert json.loads((gen_benign.OUT / f"{case['id']}.json").read_text(encoding="utf-8")) == case
    for case in build_handwritten.CASES_OUT:
        assert json.loads((build_handwritten.OUT / f"{case['id']}.json").read_text(encoding="utf-8")) == case
    assert len(list(gen_benign.OUT.glob("*.json"))) == len(gen_benign.build())
    assert len(list(build_handwritten.OUT.glob("*.json"))) == len(build_handwritten.CASES_OUT)


def test_committed_catalog_equals_generator_output():
    assert (ROOT / "spec" / "fixtures-catalog.md").read_text(encoding="utf-8") == gen_catalog.build()


def test_spec_folder_is_self_contained():
    """spec/ is copied alone into the isolated generator folder: no pointers into the code base."""
    bad = re.compile(r"(?<![\w.])(src|policy|tests|scripts|eval|fixtures)/|\.py\b|\.rego\b")
    for f in (ROOT / "spec").glob("*.md"):
        hits = bad.findall(f.read_text(encoding="utf-8"))
        assert not [h for h in hits if h], (f.name, hits[:3])


def test_validator_rejects_bad_cases():
    good = json.loads(next((ev.CASES / "attacks" / "handwritten").glob("*.json")).read_text(encoding="utf-8"))
    for mutate in (lambda d: d.update(extra=1), lambda d: d.update({"class": "nope"}),
                   lambda d: d["steps"][0].update(op="teleport"),
                   lambda d: d["steps"].append(copy.deepcopy(d["steps"][0])),
                   lambda d: d["expect"].update(final="EXECUTED")):
        d = copy.deepcopy(good)
        mutate(d)
        with pytest.raises(Exception):
            ev.Case.model_validate(d)


# ------------------------------------------------------------------ the only gate run: a throwaway executor
BY_ID = {c.id: c for c in CASES}
SANITY_ATTACKS = ["atk-pro-hidden-span-as-amount", "atk-arg-amount-lowered", "atk-evi-bbox-shows-vendor-not-amount",
                  "atk-con-vendor-outside-scope", "atk-con-self-review", "atk-spl-two-4900-concurrent",
                  "atk-rep-receipt-expired", "atk-rep-receipt-reused", "atk-rac-delegation-revoked",
                  "atk-evi-self-made-po"]
SANITY_BENIGN = ["benign-inv-b1-01", "benign-inv-b1-02", "benign-inv-b1-04", "benign-inv-img-01",
                 "benign-inv-hero-review", "benign-inv-hero-pending", "benign-ref-312", "benign-ref-420-review",
                 "benign-ref-b2-614", "benign-inv-var-01"]


def run_case(kit, case, monkeypatch):
    """Execute one case against the real gate. Returns (log, executions)."""
    import gatekit
    from psycopg.types.json import Jsonb

    from actionproof import db as dbmod
    from actionproof import gate as gate_mod
    from actionproof.gate import Principal
    from attacks._concurrency import race

    blobs, entries = ev.materialize_docs(case.setup)
    # --- seed
    dbmod.reset(kit.db)
    for login, person, roles in dbmod.PEOPLE:
        kit.sql("INSERT INTO people (login, person_id, roles) VALUES (%s, %s, %s)", (login, person, list(roles)))
    for p in case.setup.people:
        kit.sql("INSERT INTO people (login, person_id, roles) VALUES (%s, %s, %s)", (p.login, p.person_id, p.roles))
    for r in case.setup.records:
        kit.sql("INSERT INTO records (record_id, kind, data, version) VALUES (%s, %s, %s, %s)",
                (r.record_id, r.kind, Jsonb(r.data()), r.version))
    deleg = case.setup.delegations
    if deleg is None:
        ids = lambda *ks: sorted({r.__getattribute__(k) for r in case.setup.records for k in ks if getattr(r, k)})  # noqa: E731
        deleg = [ev.Delegation(on_behalf_of="user-123", max_amount="5000.00", vendors=ids("vendor_id"),
                               customers=ids("customer_id"))]
    for d in deleg:
        kit.sql("INSERT INTO delegations (on_behalf_of, max_amount, vendors, customers) VALUES (%s, %s::numeric, %s, %s)",
                (d.on_behalf_of, d.max_amount, d.vendors, d.customers))
    for i, pc in enumerate(case.setup.prior_commits):
        kit.sql("INSERT INTO commits (nonce, idempotency_key, request_hash, actor, on_behalf_of, vendor_id, amount, "
                "record_id, created_at) VALUES (%s, %s, 'prior', %s, %s, %s, %s, %s, 1)",
                (f"prior-{i}", f"prior-{i}", pc.actor, pc.on_behalf_of, pc.counterparty, pc.amount,
                 pc.record_id or f"prior:{i}"))
        if pc.record_id:
            kit.sql("UPDATE records SET data = data || jsonb_build_object('refunded', "
                    "(COALESCE(data->>'refunded', '0.00')::numeric + %s::numeric)::text) WHERE record_id = %s",
                    (pc.amount, pc.record_id))
    kit.tool.calls.clear()
    kit.refunds.calls.clear()

    clock = {"off": 0}
    real_now = gate_mod._now
    monkeypatch.setattr(gate_mod, "_now", lambda: real_now() + clock["off"])
    state: dict[str, dict] = {}
    log: list[tuple] = []

    def who(p):
        p = p or case.principal
        return Principal(p.actor, p.on_behalf_of)

    def do_prepare(s):
        wire = ev.resolve_request(s.request, case.principal, entries)
        r = kit.gate.prepare(wire, blobs, principal=who(s.principal))
        state[s.id] = {"wire": wire, "r": r}
        log.append((s.id, "prepare", r.decision, [x.rule for x in r.reasons]))

    def do_commit(s):
        src = state[s.receipt_from]
        wire = ev.merge_patch(state[s.request_from or s.receipt_from]["wire"], s.request_override or {})
        receipt = src["r"].receipt
        if receipt is not None and s.receipt_override:
            receipt = ev.merge_patch(copy.deepcopy(receipt), s.receipt_override)
        token = state[s.review_token_from].get("token") if s.review_token_from else None
        out = (lambda: kit.gate.commit(receipt, wire, token, principal=who(s.principal)))
        state[s.id] = {"redo": out}
        res = out()
        log.append((s.id, "commit", res.outcome, [x.rule for x in res.reasons]))

    def do_mint(s):
        src = state[s.receipt_from]
        wire = state[s.request_from or s.receipt_from]["wire"]
        try:
            tok = kit.gate.mint_review_token(src["r"].receipt, wire, reviewer_login=s.reviewer_login)
            state[s.id] = {"token": tok}
            log.append((s.id, "mint_token", "MINTED", []))
        except Exception as e:  # ReviewRefused or a fail-closed refusal: no token exists
            state[s.id] = {"token": None}
            log.append((s.id, "mint_token", "REFUSED", [getattr(getattr(e, "reason", None), "rule", type(e).__name__)]))

    run = {"prepare": do_prepare, "commit": do_commit, "mint_token": do_mint}
    for s in case.steps:
        if s.op in run:
            run[s.op](s)
        elif s.op == "concurrent":
            race(*[(lambda st=st: run[st.op](st)) for st in s.steps])
        elif s.op == "replay":
            res = state[s.step]["redo"]()
            log.append((s.id, "replay", res.outcome, [x.rule for x in res.reasons]))
        elif s.op == "mutate_record":
            kit.sql("UPDATE records SET data = data || %s, version = COALESCE(%s, version + 1) WHERE record_id = %s",
                    (Jsonb(s.set), s.version, s.record_id))
        elif s.op == "set_delegation":
            if s.revoke:
                kit.sql("DELETE FROM delegations WHERE on_behalf_of = %s", (s.on_behalf_of,))
            if s.max_amount is not None:
                kit.sql("UPDATE delegations SET max_amount = %s::numeric WHERE on_behalf_of = %s",
                        (s.max_amount, s.on_behalf_of))
            if s.vendors is not None:
                kit.sql("UPDATE delegations SET vendors = %s WHERE on_behalf_of = %s", (s.vendors, s.on_behalf_of))
            if s.customers is not None:
                kit.sql("UPDATE delegations SET customers = %s WHERE on_behalf_of = %s", (s.customers, s.on_behalf_of))
        elif s.op == "advance_clock":
            clock["off"] += s.seconds
    return log, len(kit.tool.calls) + len(kit.refunds.calls)


@pytest.mark.parametrize("case_id", SANITY_ATTACKS)
def test_attack_cases_execute_nothing_beyond_expectation(kit, monkeypatch, case_id):
    case = BY_ID[case_id]
    log, executions = run_case(kit, case, monkeypatch)
    assert executions <= case.expect.max_tool_executions, (log, executions)
    if case.expect.rules_any_of:  # advisory in the format; held to account here so wrong ids get fixed
        seen = {r for _, _, _, rules in log for r in rules}
        assert seen & set(case.expect.rules_any_of), (case.expect.rules_any_of, log)


@pytest.mark.parametrize("case_id", SANITY_BENIGN)
def test_benign_cases_reach_their_declared_final(kit, monkeypatch, case_id):
    case = BY_ID[case_id]
    t = time.time()
    log, executions = run_case(kit, case, monkeypatch)
    assert not [e for e in log if e[2] in ("DENY", "REFUSED")], log  # a false block
    if case.expect.final == "EXECUTED":
        assert executions == 1 and log[-1][2] == "EXECUTED", log
    else:
        assert executions == 0 and log[-1][:3] == (log[-1][0], "prepare", "REVIEW"), log
    if case.expect.rules_any_of:
        assert {r for _, _, _, rules in log for r in rules} & set(case.expect.rules_any_of), log
    assert time.time() - t < 120
