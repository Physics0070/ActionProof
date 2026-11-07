package actionproof

# ActionProof policy (Phase 3). Rules and input shape: docs/POLICY.md.
# Money is 2dp decimal strings, compared as integer cents. No floats anywhere (invariant 4).

# Default deny: any evaluation error or undefined decision falls back here (invariant 1).
default decision := {
	"outcome": "DENY",
	"reasons": [{"rule": "AP-DEFAULT", "guarantee": "G1", "msg": "no rule allowed this action"}],
}

# Cumulative per actor+vendor cap, 5000.00.
# ponytail: constant, move to data.json if per-tenant caps are needed
cap_cents := 500000

# REVIEW when abs(variance) > 100.00.
variance_limit_cents := 10000

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

# Shape check: every field the rules read must be present and typed, else DENY AP-VER-01.
well_formed if {
	input.tool == "payments.approve_invoice"
	is_string(input.actor)
	is_string(input.on_behalf_of)
	is_boolean(input.verify.ok)
	cents(input.args.amount) > 0
	is_money(input.args.variance)
	is_string(input.args.vendor_id)
	is_money(input.scope.max_amount)
	is_array(input.scope.vendors)
	every v in input.scope.vendors { is_string(v) }
	is_money(input.cumulative.committed)
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

deny contains {"rule": "AP-SCOPE-02", "guarantee": "G1", "msg": "vendor not in on_behalf_of scope"} if {
	well_formed
	not input.args.vendor_id in input.scope.vendors
}

deny contains {"rule": "AP-CUM-03", "guarantee": "G1", "msg": "actor+vendor cumulative total exceeds 5000.00"} if {
	well_formed
	cents(input.cumulative.committed) + cents(input.args.amount) > cap_cents
}

review contains {"rule": "AP-INV-04", "guarantee": "G1", "msg": "abs(invoice variance) exceeds 100.00"} if {
	well_formed
	abs_cents(cents(input.args.variance)) > variance_limit_cents
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
