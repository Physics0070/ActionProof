# ActionRequest spec (slide 4)

Strict: unknown fields are rejected (invariant 1). Amounts are decimal strings (invariant 4).

```yaml
tool: payments.approve_invoice
on_behalf_of: user-123            # caller scope, checked by AP-SCOPE-02
actor: agent-7
idempotency_key: "..."
args:
  amount: "4800.00"
    claim: DIRECT
    src: {doc: invoice.pdf, page: 1, bbox: ["72.00", "410.00", "190.00", "428.00"]}   # [x0, top, x1, bottom], pt, top-left; DECIMAL STRINGS (no floats)
    doc_sha256: ab12...
  variance: "500.00"
    claim: DERIVED
    fn: sub
    inputs: [invoice.total, po.total]
  note: "vendor says urgent"
    claim: ASSERTED
    taint: doc
```

## Claim types
| Type | Authorizes money? | Verification |
|---|---|---|
| DIRECT | yes | doc hash matches AND deterministic re-extraction at the cited page+bbox (or RFC 6901 JSON pointer) equals the value. PDF: pdfplumber and rasterize+OCR must agree. |
| DERIVED | yes | allowlisted pure function (`sub`, `add`, `sum`) over verified claims or system-of-record values; recomputed, never trusted. |
| ASSERTED | never | model-only; allowed in non-authority fields only. |

## Authority fields (registry)
| Tool | Authority fields |
|---|---|
| payments.approve_invoice | amount, variance, vendor_id, invoice_id |
| (second connector, ADR-009) | defined in Phase 4 |

Taint rule: document text may be shown to a reviewer but cannot fill an authority field unless DIRECT-verified or equal to a system-of-record value.

## Hashing
`request_hash = sha256(RFC8785(request))`. Any change after `prepare` changes the hash and invalidates the receipt.
