package actionproof

# ActionProof policy. Rules and input shape: docs/POLICY.md.
# Money is 2dp decimal strings, compared as integer cents. No floats anywhere (invariant 4).
# Two tools share every rule (ADR-009): the counterparty is the vendor (invoices) or the customer (refunds), both
# taken from the system of record by the gate, never from the request.

# Default deny: any evaluation error or undefined decision falls back here (invariant 1).
default decision := {
	"outcome": "DENY",
	"reasons": [{"rule": "AP-DEFAULT", "guarantee": "G1", "msg": "no rule allowed this action"}],
}

# Cumulative caps, 5000.00 each: per actor+counterparty AND per person (behind on_behalf_of)+counterparty (ADR-016).
# ponytail: constant, move to data.json if per-tenant caps are needed
cap_cents := 500000

# REVIEW when abs(variance) > 100.00 (invoices).
variance_limit_cents := 10000

# REVIEW when a refund amount > 1000.00 (refunds, AP-REF-13).
refund_review_cents := 100000

invoice_tool := "payments.approve_invoice"

refund_tool := "payments.refund_payment"

money_re := `^-?\d+\.\d{2}$`

is_money(s) if {
	is_string(s)
	regex.match(money_re, s)
}

# digits -> integer without to_number rejecting leading zeros ("05").
digits_int(d) := 0 if trim_left(d, "0") == ""

digits_int(d) := to_number(t) if {
	t := trim_left(d, "0")
	t != ""
}

unsigned_cents(s) := (digits_int(p[0]) * 100) + digits_int(p[1]) if p := split(s, ".")

cents(s) := unsigned_cents(s) if {
	is_money(s)
	not startswith(s, "-")
}

cents(s) := 0 - unsigned_cents(substring(s, 1, -1)) if {
	is_money(s)
	startswith(s, "-")
}

abs_cents(c) := c if c >= 0

abs_cents(c) := 0 - c if c < 0

# Per tool: who the counterparty is, which scope list holds it, and its word in reasons.
counterparty := input.args.vendor_id if input.tool == invoice_tool

counterparty := input.args.customer_id if input.tool == refund_tool

scope_ids := input.scope.vendors if input.tool == invoice_tool

scope_ids := input.scope.customers if input.tool == refund_tool

counterparty_kind := "vendor" if input.tool == invoice_tool

counterparty_kind := "customer" if input.tool == refund_tool

# Fields every tool needs.
common_well_formed if {
	is_string(input.actor)
	is_string(input.on_behalf_of)
	is_boolean(input.verify.ok)
	cents(input.args.amount) > 0
	is_money(input.scope.max_amount)
	is_money(input.cumulative.committed)
	is_money(input.cumulative.person_committed)
	is_string(counterparty)
	is_array(scope_ids)
	every v in scope_ids { is_string(v) }
}

# Shape check: every field the rules read must be present and typed, else DENY AP-VER-01.
well_formed if {
	input.tool == invoice_tool
	common_well_formed
	is_money(input.args.variance)
}

well_formed if {
	input.tool == refund_tool
	common_well_formed
}

deny contains {"rule": "AP-VER-01", "guarantee": "G1", "msg": "malformed or unsupported policy input"} if {
	not well_formed
}

deny contains {"rule": "AP-VER-01", "guarantee": "G1", "msg": "verification failed"} if {
	input.verify.ok == false
}

deny contains {"rule": "AP-SCOPE-02", "guarantee": "G1", "msg": "amount exceeds on_behalf_of scope max_amount"} if {
	well_formed
	cents(input.args.amount) > cents(input.scope.max_amount)
}

deny contains {"rule": "AP-SCOPE-02", "guarantee": "G1", "msg": sprintf("%s not in on_behalf_of scope", [counterparty_kind])} if {
	well_formed
	not counterparty in scope_ids
}

deny contains {"rule": "AP-CUM-03", "guarantee": "G1", "msg": sprintf("actor+%s cumulative total exceeds 5000.00", [counterparty_kind])} if {
	well_formed
	actor_over_cap
}

actor_over_cap if cents(input.cumulative.committed) + cents(input.args.amount) > cap_cents

# ADR-016: actor rotation (agent-7 then agent-8 for the same person) must not reset the cap. Only reported when the
# actor cap holds, so one over-cap request carries one AP-CUM-03 reason.
deny contains {"rule": "AP-CUM-03", "guarantee": "G1", "msg": sprintf("person+%s cumulative total exceeds 5000.00", [counterparty_kind])} if {
	well_formed
	not actor_over_cap
	cents(input.cumulative.person_committed) + cents(input.args.amount) > cap_cents
}

review contains {"rule": "AP-INV-04", "guarantee": "G1", "msg": "abs(invoice variance) exceeds 100.00"} if {
	well_formed
	input.tool == invoice_tool
	abs_cents(cents(input.args.variance)) > variance_limit_cents
}

review contains {"rule": "AP-REF-13", "guarantee": "G1", "msg": "refund amount exceeds 1000.00"} if {
	well_formed
	input.tool == refund_tool
	cents(input.args.amount) > refund_review_cents
}

# Precedence: any DENY wins; else REVIEW; else ALLOW. Reasons explain the outcome.
decision := {"outcome": "DENY", "reasons": [r | some r in deny]} if count(deny) > 0

decision := {"outcome": "REVIEW", "reasons": [r | some r in review]} if {
	count(deny) == 0
	count(review) > 0
}

decision := {"outcome": "ALLOW", "reasons": []} if {
	count(deny) == 0
	count(review) == 0
}
