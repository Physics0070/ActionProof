---------------------------- MODULE ActionProof ----------------------------
(* Bounded model of the ActionProof commit / execution protocol (ADR-006, ADR-010, ADR-022, ADR-029).
   It models the DURABLE reservation written before the downstream call, crashes, ambiguous outcomes and
   evidence-based reconciliation. It is a model of the design, not a proof of the Python code: see formal/README.md
   and formal/MAPPING.md for what each action stands for and what is NOT modelled. *)
EXTENDS Naturals, FiniteSets, Sequences

CONSTANT Cap  \* the cumulative cap (cents); the real value is 500000 (5000.00), scaled down to keep the model small

(* ---- the bounded instance: three prepared receipts, two logical requests, one review token ---- *)
Nonces == {"n1", "n2", "n3"}
Keys   == {"k1", "k2"}
Tokens == {"t1"}
KeyOf  == [n \in Nonces |-> IF n = "n3" THEN "k2" ELSE "k1"]   \* n1, n2 are two receipts for the SAME request key
Amt    == [n \in Nonces |-> 3]
Review == {"n1", "n2"}                                         \* receipts whose decision is REVIEW (need a token)
TokKey == [t \in Tokens |-> "k1"]                              \* a token binds to one request (request_hash ~ key)

RECURSIVE SumOf(_)
SumOf(S) == IF S = {} THEN 0 ELSE LET x == CHOOSE y \in S : TRUE IN Amt[x] + SumOf(S \ {x})

VARIABLES
  exec,        \* nonce -> lifecycle state
  prepared,    \* receipts issued by prepare
  held,        \* durable spending reservations (the `reservations` view: counted against the caps)
  effect,      \* nonce -> the downstream side effect has happened
  inflight,    \* nonce -> a dispatched call may still land (ambiguity)
  tokUsed,     \* review tokens consumed
  tokCommits,  \* token -> number of commits it authorized
  resCount,    \* nonce -> reservations ever created for it
  journal      \* append-only execution journal (event names of ADR-029)

vars == <<exec, prepared, held, effect, inflight, tokUsed, tokCommits, resCount, journal>>

States == {"none", "reserved", "dispatched", "confirmed", "failed", "unknown", "resolved_done", "resolved_failed"}

Init == /\ exec = [n \in Nonces |-> "none"] /\ prepared = {} /\ held = {}
        /\ effect = [n \in Nonces |-> FALSE] /\ inflight = [n \in Nonces |-> FALSE]
        /\ tokUsed = {} /\ tokCommits = [t \in Tokens |-> 0] /\ resCount = [n \in Nonces |-> 0] /\ journal = <<>>

KeyHeld(k) == \E m \in held : KeyOf[m] = k
TokenFree(n) == \E t \in Tokens : TokKey[t] = KeyOf[n] /\ t \notin tokUsed

(* prepare: a signed receipt exists (G1 checks are outside this model: it starts after a receipt is issued). *)
Prepare(n) == /\ n \notin prepared /\ prepared' = prepared \cup {n}
              /\ UNCHANGED <<exec, held, effect, inflight, tokUsed, tokCommits, resCount, journal>>

(* commit step 1, atomic under the commit lane lock: nonce/key uniqueness, cap check, token available, then the
   durable reservation (tool_reached) is written BEFORE any dispatch. *)
Reserve(n) == /\ n \in prepared /\ exec[n] = "none" /\ resCount[n] = 0
              /\ ~KeyHeld(KeyOf[n])                      \* UNIQUE idempotency key over unresolved/committed work (AP-REP-05)
              /\ SumOf(held \cup {n}) <= Cap              \* cumulative cap incl. every reservation (AP-CUM-03)
              /\ (n \in Review => TokenFree(n))           \* REVIEW needs an unused token bound to this request
              /\ exec' = [exec EXCEPT ![n] = "reserved"] /\ held' = held \cup {n}
              /\ resCount' = [resCount EXCEPT ![n] = @ + 1]
              /\ journal' = Append(journal, [ev |-> "RESERVATION_CREATED", n |-> n])
              /\ UNCHANGED <<prepared, effect, inflight, tokUsed, tokCommits>>

(* commit step 2: the journal records DISPATCH_STARTED, then the downstream call is issued. *)
Dispatch(n) == /\ exec[n] = "reserved"
               /\ exec' = [exec EXCEPT ![n] = "dispatched"] /\ inflight' = [inflight EXCEPT ![n] = TRUE]
               /\ journal' = Append(journal, [ev |-> "DISPATCH_STARTED", n |-> n])
               /\ UNCHANGED <<prepared, held, effect, tokUsed, tokCommits, resCount>>

(* environment: the call lands (the side effect happens), possibly after the process crashed. *)
Land(n) == /\ inflight[n] /\ ~effect[n]
           /\ effect' = [effect EXCEPT ![n] = TRUE] /\ inflight' = [inflight EXCEPT ![n] = FALSE]
           /\ UNCHANGED <<exec, prepared, held, tokUsed, tokCommits, resCount, journal>>

(* environment: the call is definitively rejected / never delivered (trustworthy downstream evidence). *)
Drop(n) == /\ inflight[n] /\ ~effect[n]
           /\ inflight' = [inflight EXCEPT ![n] = FALSE]
           /\ UNCHANGED <<exec, prepared, held, effect, tokUsed, tokCommits, resCount, journal>>

(* commit step 3a: success is CONFIRMED only after the effect is observed; the main tx commits and consumes the token. *)
Confirm(n) == /\ exec[n] = "dispatched" /\ effect[n]
              /\ \/ /\ n \in Review
                    /\ \E t \in Tokens : TokKey[t] = KeyOf[n] /\ t \notin tokUsed
                                          /\ tokUsed' = tokUsed \cup {t}
                                          /\ tokCommits' = [tokCommits EXCEPT ![t] = @ + 1]
                 \/ /\ n \notin Review /\ UNCHANGED <<tokUsed, tokCommits>>
              /\ exec' = [exec EXCEPT ![n] = "confirmed"]
              /\ journal' = Append(journal, [ev |-> "EXECUTION_CONFIRMED", n |-> n])
              /\ UNCHANGED <<prepared, held, effect, inflight, resCount>>

(* commit step 3b: a definite failure (no effect, nothing in flight): the reservation is BURNED (stays counted, ADR-010). *)
Fail(n) == /\ exec[n] = "dispatched" /\ ~effect[n] /\ ~inflight[n]
           /\ exec' = [exec EXCEPT ![n] = "failed"]
           /\ journal' = Append(journal, [ev |-> "EXECUTION_FAILED", n |-> n])
           /\ UNCHANGED <<prepared, held, effect, inflight, tokUsed, tokCommits, resCount>>

(* the process dies / the connection drops / serialization fails after reservation or dispatch: outcome AMBIGUOUS.
   Nothing is released and an in-flight call is NOT cancelled. *)
Crash(n) == /\ exec[n] \in {"reserved", "dispatched"}
            /\ exec' = [exec EXCEPT ![n] = "unknown"]
            /\ journal' = Append(journal, [ev |-> "EXECUTION_UNKNOWN", n |-> n])
            /\ UNCHANGED <<prepared, held, effect, inflight, tokUsed, tokCommits, resCount>>

(* reconciliation with trustworthy evidence (or an authorized human decision that matches reality). There is NO action
   that resolves an unknown execution because time elapsed. *)
ReconcileDone(n) == /\ exec[n] = "unknown" /\ effect[n]
                    /\ exec' = [exec EXCEPT ![n] = "resolved_done"]
                    /\ journal' = Append(journal, [ev |-> "RECONCILIATION_COMPLETED", n |-> n])
                    /\ UNCHANGED <<prepared, held, effect, inflight, tokUsed, tokCommits, resCount>>

ReconcileFailed(n) == /\ exec[n] = "unknown" /\ ~effect[n] /\ ~inflight[n]   \* evidence: it did not and cannot happen
                      /\ exec' = [exec EXCEPT ![n] = "resolved_failed"] /\ held' = held \ {n}
                      /\ journal' = Append(journal, [ev |-> "RECONCILIATION_COMPLETED", n |-> n])
                      /\ UNCHANGED <<prepared, effect, inflight, tokUsed, tokCommits, resCount>>

Next == \E n \in Nonces : Prepare(n) \/ Reserve(n) \/ Dispatch(n) \/ Land(n) \/ Drop(n) \/ Confirm(n) \/ Fail(n)
                          \/ Crash(n) \/ ReconcileDone(n) \/ ReconcileFailed(n)

Spec == Init /\ [][Next]_vars

(* ------------------------------------------------------------------ safety properties *)
TypeOK == /\ exec \in [Nonces -> States] /\ prepared \subseteq Nonces /\ held \subseteq Nonces
          /\ effect \in [Nonces -> BOOLEAN] /\ inflight \in [Nonces -> BOOLEAN]
          /\ tokUsed \subseteq Tokens /\ tokCommits \in [Tokens -> Nat] /\ resCount \in [Nonces -> Nat]

\* G2: no nonce creates more than one logical execution reservation.
ResOnce == \A n \in Nonces : resCount[n] <= 1
\* G2: no request idempotency key holds more than one reservation (so it authorizes one logical execution).
KeyOnce == \A k \in Keys : Cardinality({n \in held : KeyOf[n] = k}) <= 1
\* G2: the downstream effect happens at most once per request key (no double effect).
KeyEffectOnce == \A k \in Keys : Cardinality({n \in Nonces : KeyOf[n] = k /\ effect[n]}) <= 1
\* G2: a review token authorizes at most one commit.
TokenOnce == \A t \in Tokens : tokCommits[t] <= 1
\* Spending integrity: reserved spending never exceeds the cap.
SpendCap == SumOf(held) <= Cap
\* Unknown executions keep their reservation until resolved.
UnknownHeld == \A n \in Nonces : exec[n] = "unknown" => n \in held
\* Execution integrity: no effect (or in-flight call) without a durable reservation.
DispatchNeedsReservation == \A n \in Nonces : (effect[n] \/ inflight[n]) => n \in held
\* Honest records: CONFIRMED only after the effect happened; a released reservation never had an effect.
ConfirmedTruthful == \A n \in Nonces : exec[n] = "confirmed" => effect[n]
ReleasedHadNoEffect == \A n \in Nonces : exec[n] = "resolved_failed" => (~effect[n] /\ ~inflight[n])
\* Journal order: every dispatch is preceded by its reservation event.
JournalOrder == \A i \in 1..Len(journal) :
                  journal[i].ev = "DISPATCH_STARTED" =>
                    \E j \in 1..(i - 1) : journal[j].ev = "RESERVATION_CREATED" /\ journal[j].n = journal[i].n

(* Recovery integrity (action property): an UNKNOWN execution is never re-dispatched or re-confirmed; it only stays
   unknown or is resolved by reconciliation. *)
NoRedispatch == [][\A n \in Nonces : exec[n] = "unknown" =>
                      exec'[n] \in {"unknown", "resolved_done", "resolved_failed"}]_vars

=============================================================================
