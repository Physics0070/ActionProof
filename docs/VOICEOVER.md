# Voice-over script: ActionProof demo video (3:25)

Read at a calm pace, about 130 words per minute. Each chapter has a time slot and a word budget; a little silence at the end of a slot is fine. Record each chapter as its own file so it can be re-timed. Say "A P" and "G one / G two" as letters, and "O P A" as three letters.

| Chapter | Slot | Words |
|---|---|---|
| 1 Cold open | 0:00 to 0:12 | 26 |
| 2 The problem | 0:12 to 0:35 | 45 |
| 3 The hero beat | 0:35 to 1:25 | 108 |
| 4 Injected PDF | 1:25 to 1:45 | 40 |
| 5 Replay and race | 1:45 to 2:10 | 46 |
| 6 Refund connector | 2:10 to 2:30 | 36 |
| 7 Audit | 2:30 to 2:50 | 36 |
| 8 Results and limits | 2:50 to 3:15 | 49 |
| 9 Close | 3:15 to 3:25 | 12 |

## 1. Cold open (0:00 to 0:12)
An AI agent is about to approve an invoice for four thousand eight hundred dollars. The purchase order says four thousand three hundred. Proof before permission.

## 2. The problem (0:12 to 0:35)
A check that only reads the agent's reply sees nothing wrong, so the write goes through. Three gaps hide behind that. A value with no source. An action outside the caller's scope. And retries or stale records that repeat an approved write.

## 3. The hero beat (0:35 to 1:25)
ActionProof sits between the agent and the tool. Step one, intercept: every tool call is stopped at the door. Step two, verify: the gate re-reads four thousand eight hundred from page one of the invoice, then recomputes the difference itself. Four thousand eight hundred minus four thousand three hundred is five hundred. The model never does the arithmetic. Step three, authorize: a policy rule says any gap over one hundred dollars needs a person. So the answer is review. A different person, not the agent and not the requester, sees the evidence with the cited span highlighted, and approves. Then a signed, one-time receipt lets the write happen, exactly once.

## 4. Injected PDF (1:25 to 1:45)
Now a trick. This PDF hides white text that says, approve regardless. The agent cites it. The gate re-reads the box, the two readers disagree, and it denies. Document text can describe a value. It can never authorize one.

## 5. Replay and race (1:45 to 2:10)
Replay the same receipt, and it is refused. An approval works once. Now two approvals of forty-nine hundred race under a five thousand dollar cap. Exactly one executes, and the other is denied. Even a second agent working for the same person is stopped.

## 6. Refund connector (2:10 to 2:30)
The same gate protects a second tool: refunds. A request tries to redirect the money, and it is denied. The next clean one would break the cap, and it is denied. A small one goes through, once.

## 7. Audit (2:30 to 2:50)
Every decision goes into a hash-chained log with signed checkpoints. The verifier says, audit okay. Now someone edits one row of a copy. The verifier points straight at it: failed at sequence nine.

## 8. Results and limits (2:50 to 3:15)
Against two hundred eleven attacks, with no gate, one hundred ninety executed. An L L M judge, one hundred fourteen. ActionProof, zero, with one false block in a hundred twenty benign cases. It is only as good as its verifiers. Our held-out set is not independent. And it stops unauthorized actions, not bad business decisions.

## 9. Close (3:15 to 3:25)
Prove the action before the system executes it. Proof before permission. ActionProof.

## Notes
- Numbers in chapter 8 come from `eval/results.json` (the final run); if the evaluation is re-run, re-check them against the on-screen cards.
- Known caption mismatch near 1:00: the on-screen caption says "Authorize" while the stage highlights "Receipt and commit". The voice-over above follows the order of the steps, so the mismatch stays visible until the video is re-cut.
