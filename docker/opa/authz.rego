# OPA is reachable on a public URL on free hosting: allow ONLY the gateway's decision query and the health probe.
# Everything else (policy PUT/DELETE, data writes, other reads) is denied, so no one can replace the rules (G1).
package system.authz

default allow := false

allow if {
	input.method == "POST"
	input.path == ["v1", "data", "actionproof", "decision"]
}

allow if {
	input.method == "GET"
	input.path == ["health"]
}

# ADR-028: read-only provenance. The gateway reads the loaded policy text (to derive the policy revision) and the OPA
# version. Both are GETs and the policy is public in the repository; nothing here can change a rule.
allow if {
	input.method == "GET"
	input.path == ["v1", "policies"]
}

allow if {
	input.method == "GET"
	input.path == ["v1", "data", "system", "version"]
}
