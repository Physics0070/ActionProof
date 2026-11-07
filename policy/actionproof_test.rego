package actionproof_test

import data.actionproof

# Hero request: in scope, verified, committed 0.00, variance 500.00 -> REVIEW (AP-INV-04).
hero := {
	"tool": "payments.approve_invoice",
	"actor": "agent-7",
	"on_behalf_of": "user-123",
	"verify": {"ok": true, "reasons": []},
	"args": {"amount": "4800.00", "variance": "500.00", "vendor_id": "V-ACME"},
	"scope": {"max_amount": "5000.00", "vendors": ["V-ACME"]},
	"cumulative": {"committed": "0.00"},
}

with_args(patch) := object.union(hero, {"args": object.union(hero.args, patch)})

with_committed(c) := object.union(hero, {"cumulative": {"committed": c}})

# variance 0 so only the rule under test can fire
clean(patch) := with_args(object.union({"variance": "0.00"}, patch))

d(inp) := x if x := actionproof.decision with input as inp

rules(inp) := {r.rule | some r in d(inp).reasons}

test_hero_review_inv04 if {
	d(hero).outcome == "REVIEW"
	d(hero).reasons == [{"rule": "AP-INV-04", "guarantee": "G1", "msg": "abs(invoice variance) exceeds 100.00"}]
}

test_inv04_variance_100_00_allow if {
	d(with_args({"variance": "100.00"})) == {"outcome": "ALLOW", "reasons": []}
}

test_inv04_variance_100_01_review if {
	d(with_args({"variance": "100.01"})).outcome == "REVIEW"
	rules(with_args({"variance": "100.01"})) == {"AP-INV-04"}
}

test_inv04_variance_negative_100_01_review if {
	d(with_args({"variance": "-100.01"})).outcome == "REVIEW"
}

test_inv04_variance_negative_100_00_allow if {
	d(with_args({"variance": "-100.00"})).outcome == "ALLOW"
}

test_inv04_variance_negative_500_review if {
	d(with_args({"variance": "-500.00"})).outcome == "REVIEW"
}

test_ver01_verify_false_deny if {
	inp := object.union(hero, {"verify": {"ok": false, "reasons": []}})
	d(inp).outcome == "DENY"
	"AP-VER-01" in rules(inp)
	every r in d(inp).reasons { r.guarantee == "G1" }
}

test_ver01_empty_input_deny if {
	d({}).outcome == "DENY"
	rules({}) == {"AP-VER-01"}
}

test_ver01_float_amount_deny if {
	inp := with_args({"amount": 4800})
	d(inp).outcome == "DENY"
	rules(inp) == {"AP-VER-01"}
}

test_ver01_bad_money_strings_deny if {
	every s in ["4800", "4800.0", "4800.000", "1e3", "+5.00", " 5.00", "5.00 ", "", "-"] {
		d(clean({"amount": s})).outcome == "DENY"
		rules(clean({"amount": s})) == {"AP-VER-01"}
	}
}

test_ver01_bad_variance_deny if {
	d(with_args({"variance": "500"})).outcome == "DENY"
}

test_ver01_nonpositive_amount_deny if {
	d(clean({"amount": "0.00"})).outcome == "DENY"
	d(clean({"amount": "-1.00"})).outcome == "DENY"
}

test_ver01_unknown_tool_deny if {
	d(object.union(hero, {"tool": "payments.delete_vendor"})).outcome == "DENY"
}

test_ver01_missing_scope_deny if {
	inp := object.remove(hero, ["scope"])
	d(inp).outcome == "DENY"
	rules(inp) == {"AP-VER-01"}
}

test_ver01_leading_zero_money_ok if {
	d(clean({"amount": "0050.05"})).outcome == "ALLOW"
}

test_scope02_amount_equal_max_allow if {
	d(clean({"amount": "5000.00"})) == {"outcome": "ALLOW", "reasons": []}
}

test_scope02_amount_max_plus_cent_deny if {
	inp := clean({"amount": "5000.01"})
	d(inp).outcome == "DENY"
	"AP-SCOPE-02" in rules(inp)
}

test_scope02_vendor_out_of_scope_deny if {
	inp := clean({"vendor_id": "V-EVIL"})
	d(inp).outcome == "DENY"
	rules(inp) == {"AP-SCOPE-02"}
}

test_cum03_0_plus_4900_allow if {
	d(object.union(clean({"amount": "4900.00"}), {"cumulative": {"committed": "0.00"}})).outcome == "ALLOW"
}

test_cum03_4900_plus_4900_deny if {
	inp := object.union(clean({"amount": "4900.00"}), {"cumulative": {"committed": "4900.00"}})
	d(inp).outcome == "DENY"
	rules(inp) == {"AP-CUM-03"}
}

test_cum03_100_plus_4900_equal_cap_allow if {
	d(object.union(clean({"amount": "4900.00"}), {"cumulative": {"committed": "100.00"}})).outcome == "ALLOW"
}

test_cum03_cap_plus_cent_deny if {
	inp := object.union(clean({"amount": "4900.00"}), {"cumulative": {"committed": "100.01"}})
	rules(inp) == {"AP-CUM-03"}
}

test_precedence_deny_beats_review if {
	# hero variance 500.00 would REVIEW; vendor out of scope DENYs
	inp := with_args({"vendor_id": "V-EVIL"})
	d(inp).outcome == "DENY"
	rules(inp) == {"AP-SCOPE-02"}
}

test_multiple_denies_all_returned if {
	inp := object.union(with_args({"amount": "6000.00", "vendor_id": "V-EVIL"}), {"verify": {"ok": false, "reasons": []}})
	rules(inp) == {"AP-VER-01", "AP-SCOPE-02", "AP-CUM-03"}
	count(d(inp).reasons) == 4
}
