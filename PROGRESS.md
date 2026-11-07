# PROGRESS

## Phase 1 — Foundation: OPEN (infra check blocked)
- Built: pyproject + uv env, compose (postgres, opa sidecar), policy stub, all Phase 1 docs, DECK_TRACE, subagents, Tesseract 5.5.3 installed.
- Check: `pytest tests/test_smoke.py` passes. `tests/test_infra.py` (postgres + OPA reachable) NOT run: Docker Desktop engine would not start (needs user).
- USP: pending infra gate.

## Phase 2 — Claims (W1): code gate passed
- Built: contracts.py (strict, RFC 8785), fixtures (53 docs, manifest, hero), extract.py (pdfplumber + raster/OCR dual check, JSON pointer), verify.py (DIRECT/DERIVED/ASSERTED, taint, fail closed, unknown args denied), THREAT_MODEL, TESTING.
- Check: `python -m uv run pytest -q -m "not infra"` -> 212 passed, 2 deselected (run by controller, not only by subagents). OCR agreed with the text layer on 27/27 fixture totals.
- USP: G1 proven for the claim layer: a value that does not re-extract at its cited span, a wrong document hash, a model-claimed derived value (501.00), an ASSERTED money field, a doc-tainted authority field and an unknown argument all fail verification with rule AP-VER-01 / G1; no verifier error can pass.
- Open issues: OCR may read `$` as `S` on other machines (fails closed); exact-compare means a dropped comma becomes a false block (measure in Phase 6); gate decision of ALLOW/REVIEW thresholds is Phase 3 (variance = invoice - po, AP-INV-04 on abs(variance) > 100).
- Next: Phase 3 (needs Docker for OPA and Postgres).
