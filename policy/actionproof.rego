package actionproof

# Phase 1 stub: default deny. Phase 3 replaces this with AP-VER-01..AP-INV-04.
default decision := {
	"outcome": "DENY",
	"reasons": [{"rule": "AP-DEFAULT", "guarantee": "G1", "msg": "no rule allowed this action"}],
}
