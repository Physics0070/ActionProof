# Performance budget (Lighthouse, mobile preset)

`web/lighthouserc.json` asserts LCP <= 3200 ms and performance >= 0.75 (median of 3 runs, simulated slow 4G + 4x CPU,
WebGL forced on through SwiftShader). Google's "good" LCP is 2500 ms, so this is NOT yet at the good line.

Measured (2026-11-23):
- First paint of the hero text is at about 0.75 s in the Lighthouse filmstrip; the recorded-decision card is filled in by
  about 1.9 s. The lab figure (LCP about 2.7-3.3 s, TBT about 1.8 s) is Lighthouse's *simulated* throttled estimate.
- The remaining main-thread cost is React hydration of the whole home page (one chunk, about 1.2 s at 4x slowdown).
- Done: the 3D scene and the scroll driver now start on the first interaction (pointer, key, touch, scroll) or after 8 s,
  not at load. Tried without effect: `font-display: optional`, delaying the driver by a timer (reverted).
- Not done: shrinking hydration (split the home page into server components, island the story). Upgrade path to reach
  LCP <= 2500 and performance >= 0.85.
- Local Lighthouse against a build with `Cross-Origin-Opener-Policy: same-origin` fails with NO_NAVSTART (a known tracing
  limitation); CI's lhci run is unaffected.

# Commit lane (Gate.commit locking, ADR-036)

Question: would replacing the global commit lane (`LOCK TABLE commits IN SHARE ROW EXCLUSIVE MODE`) with a per-(actor,
counterparty) lock raise commit throughput? Measured first, with `scripts/bench_commit_lanes.py` (real local Postgres
16.9 on port 5433 + real OPA over `policy/`, the unchanged gate code, the mock payments adapter; one Windows laptop,
client threads in one Python process, connections pre-pooled so no point pays a connect: 0 new connections in all 48 points).

Method: per point, 200 invoices of 1.00 are prepared (not timed), then committed by 1, 4, 8 or 16 threads; 3 reps per
point. `same` = every commit on one (actor, vendor) pair; `spread` = every commit on its own vendor. `lane` = production;
`no_lane` = a bench-only connection wrapper drops the LOCK TABLE commits statement, leaving only the audit lock: the upper
bound of ANY lane replacement. Attribution is wall-clock timing (not pg_stat_activity) around the two LOCK statements
and from the first audit-lock acquisition to the transaction end, plus `time.thread_time()` per commit. After every point
the stress-test invariants were re-checked (executes == commits rows, unique nonces and keys, per-pair and per-person
totals <= 5000.00, audit chain verifies): all 48 points executed 200/200 with no denials.

Measured 2026-11-23 (median of 3 reps, [min-max]; waits/holds are per-commit means, median over reps):

| variant | layout | workers | commits/s | p50 ms | p95 ms | lane wait | audit wait | audit hold | thread CPU | total ms |
|---|---|---|---|---|---|---|---|---|---|---|
| lane | same | 1 | 12.8 [12.6-13.0] | 74.4 [72.6-74.8] | 100.6 [97.5-104.4] | 0.6 | 2.9 | 74.1 | 40.2 | 78.2 |
| lane | same | 4 | 13.2 [13.1-13.8] | 284.3 [278.0-293.7] | 365.4 [339.2-426.7] | 220.3 | 3.5 | 73.6 | 43.0 | 298.7 |
| lane | same | 8 | 13.2 [12.7-13.4] | 572.6 [562.2-582.4] | 732.2 [696.5-841.7] | 512.4 | 3.5 | 73.6 | 41.2 | 590.9 |
| lane | same | 16 | 12.2 [11.0-12.2] | 1174.1 [1173.5-1412.3] | 1710.2 [1683.6-2027.6] | 1163.9 | 3.5 | 80.1 | 42.0 | 1249.2 |
| lane | spread | 1 | 12.7 [12.0-13.6] | 74.1 [71.0-80.5] | 104.0 [97.9-105.5] | 0.6 | 2.9 | 74.1 | 42.7 | 78.5 |
| lane | spread | 4 | 13.5 [13.4-13.8] | 278.4 [277.2-289.0] | 342.2 [341.0-374.4] | 215.1 | 3.4 | 72.1 | 40.6 | 291.9 |
| lane | spread | 8 | 13.6 [13.2-13.8] | 555.9 [545.0-558.0] | 738.0 [709.3-754.4] | 496.6 | 3.4 | 71.8 | 42.4 | 573.1 |
| lane | spread | 16 | 12.6 [11.1-12.7] | 1210.7 [1132.2-1327.2] | 1781.7 [1758.2-1951.3] | 1132.9 | 3.3 | 77.9 | 42.6 | 1216.1 |
| no_lane | same | 1 | 12.2 [11.2-14.3] | 80.2 [71.4-85.5] | 104.7 [101.0-110.4] | 0.0 | 3.2 | 78.3 | 44.4 | 81.8 |
| no_lane | same | 4 | 14.4 [13.6-15.4] | 262.9 [242.8-280.4] | 363.1 [331.3-479.7] | 0.0 | 205.1 | 69.0 | 39.7 | 275.2 |
| no_lane | same | 8 | 12.7 [12.3-13.4] | 612.6 [568.7-618.6] | 794.8 [715.7-807.2] | 0.0 | 536.1 | 78.1 | 46.7 | 615.5 |
| no_lane | same | 16 | 10.8 [10.0-12.9] | 1318.4 [1108.1-1407.3] | 2233.0 [2065.8-2509.2] | 0.0 | 1310.6 | 91.5 | 47.0 | 1404.2 |
| no_lane | spread | 1 | 12.8 [11.2-13.1] | 74.8 [73.5-87.5] | 97.0 [95.4-114.6] | 0.0 | 2.9 | 74.4 | 42.7 | 78.0 |
| no_lane | spread | 4 | 13.3 [12.3-13.3] | 314.1 [283.5-333.4] | 414.5 [392.5-421.4] | 0.0 | 223.3 | 74.3 | 43.5 | 298.5 |
| no_lane | spread | 8 | 12.5 [9.5-13.0] | 586.7 [570.4-776.1] | 872.8 [747.0-1270.7] | 0.0 | 542.3 | 79.2 | 43.9 | 623.1 |
| no_lane | spread | 16 | 11.4 [11.3-11.4] | 1250.2 [1238.9-1297.1] | 2079.1 [1882.7-2636.0] | 0.0 | 1255.1 | 87.1 | 45.5 | 1344.4 |

Reading:
- Throughput is flat at about 11-14 commits/s from 1 to 16 workers, for one pair and for distinct pairs alike: commits
  are fully serialised. Added workers only add queueing (p50 grows linearly with workers).
- The audit lock is held for about 72-80 ms of a 78 ms commit at 1 worker (~95%): it is taken right after the lane, at
  the start of the transaction, and held to the end (policy re-check over HTTP to OPA, the marker + journal writes on
  their own connections, the tool call, the confirmed journal event, the EXECUTED audit entry, commit).
- With the lane, the wait shows up as lane wait and the audit wait stays ~3 ms; with no lane at all the same wait simply
  moves to the audit lock, and throughput does not rise (within the rep spread). So the lane costs nothing extra, and no
  per-(actor, vendor) lock can help while every commit takes the audit lock for its whole length.
- About 40-47 ms of each commit is Python thread CPU (signature checks, canonicalisation, the signed audit entry), so a
  single-process client is also near its GIL ceiling; that does not change the conclusion (the hold is the serial part).

Decision: locking NOT changed. The upgrade that can raise throughput is audit sequencing: allocate `audit_log.seq` from a
sequence (or per-commit staging rows) and link the hash chain in a single chain-writer after commit, so the commit tx no
longer holds an EXCLUSIVE audit lock for its whole length; only then would per-(actor, counterparty) advisory locks (taken
in a lock order compatible with "audit first", the cross-vendor and per-person cap checks kept) parallelise anything.
Re-run `python scripts/bench_commit_lanes.py --n 200 --reps 3` after any such change.
