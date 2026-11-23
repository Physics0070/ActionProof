"""Asynchronous anchor publisher and monitor (ADR-030): a separate process, never part of a decision.

    python -m actionproof.anchor_publisher once    publish every unpublished checkpoint in seq order, then exit
    python -m actionproof.anchor_publisher check   verify the remote against the database, publish nothing
    python -m actionproof.anchor_publisher run     `once` every ANCHOR_PUBLISH_INTERVAL_SECONDS, forever

Each cycle: (1) list and re-verify the remote (signatures through the KeyRegistry, strictly increasing seq);
(2) read the database in ONE short READ ONLY REPEATABLE READ transaction, then commit and close it; (3) compare;
(4) only then make HTTP requests. No HTTP request is ever made while a database transaction is open, the audit lock is
never taken, nothing is written to the database, and the Gate does not import this module: an unreachable or lying
remote cannot block or change an authorization decision. The remote is listed BEFORE the snapshot, so a checkpoint a
concurrent publisher adds in between is never mistaken for "remote ahead of the database".

Detected (exit 1): a remote checkpoint whose head differs from the local chain at that seq (conflict / rewritten
history); the remote missing a checkpoint the database holds below the remote head (gap); the remote behind the head
this monitor verified before (remote rollback, needs ANCHOR_STATE_PATH); the database shorter than the remote head
(local chain rewound); in `check` also the full local chain (audit.verify). Lag: the oldest unpublished checkpoint
older than ANCHOR_MAX_LAG_SECONDS is exit 1 ("LAG"). An unreachable remote in `once`/`run` is a WARN (exit 0) while
within the lag budget; `check` without the remote is exit 1. Recovery: the next cycle publishes from the remote head
upwards, in order; a failure stops the cycle at that seq, so nothing is skipped or reordered.
Exit 2: config error. Output never holds the token or the database URL.

Two streams (ADR-034), each cycle publishes and checks both, audit first, independently and never mixed:
  audit    audit_checkpoints over audit_log             {ANCHOR_REMOTE_URL}/checkpoints          state ANCHOR_STATE_PATH
  journal  execution_journal_checkpoints over the       {ANCHOR_REMOTE_URL}/journal/checkpoints  state
           execution journal (journal.checkpoint)                                                ANCHOR_STATE_PATH.journal
Report lines are prefixed `anchor-remote:` (audit) and `anchor-remote[journal]:`; the exit code is the worst of the
two. Every rule above (order, lag, rollback, gap, rewind, no HTTP inside a transaction) holds per stream.
"""
import argparse
import json
import math
import os
import sys
import time
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
from pydantic import BaseModel, ConfigDict, SecretStr, ValidationError, field_validator

from actionproof import audit, journal
from actionproof.anchor import AnchorError
from actionproof.anchor_remote import HttpAnchor, RemoteUnavailable
from actionproof.config import ConfigError
from actionproof.signing import KeyRegistry

_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


class PublisherSettings(BaseModel):
    """Validated env (invariant 7). The remote's URL and token are their own settings: never the database's
    credentials, and the publisher has no access to any private key (public KeyRegistry only)."""
    model_config = ConfigDict(extra="forbid", frozen=True)

    database_url: SecretStr
    key_registry_path: str
    anchor_remote_url: str
    anchor_remote_token: SecretStr
    # Last remote head this monitor verified ({seq, head_hash}); keep it with the monitor, not on the database host.
    anchor_state_path: str
    anchor_remote_timeout_seconds: float = 5.0
    anchor_max_lag_seconds: int = 300
    anchor_publish_interval_seconds: float = 10.0

    @field_validator("key_registry_path", "anchor_state_path")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must be non-empty")
        return v

    @field_validator("anchor_remote_url")
    @classmethod
    def _url(cls, v: str) -> str:
        u = urlsplit(v)
        if u.scheme not in ("http", "https") or not u.hostname or u.username or u.password or u.query or u.fragment:
            raise ValueError("must be an http(s) URL without credentials, query or fragment")
        if u.scheme == "http" and u.hostname not in _LOOPBACK:
            raise ValueError("plain http only to loopback (a local stub); use https")
        return v

    @field_validator("anchor_remote_token")
    @classmethod
    def _token(cls, v: SecretStr) -> SecretStr:
        if len(v.get_secret_value().strip()) < 16:
            raise ValueError("must be at least 16 characters")
        return v

    @field_validator("anchor_remote_timeout_seconds", "anchor_max_lag_seconds", "anchor_publish_interval_seconds")
    @classmethod
    def _positive(cls, v):
        if not (math.isfinite(v) and v > 0):
            raise ValueError("must be > 0")
        return v


_ENV = {name: name.upper() for name in PublisherSettings.model_fields}


def load_settings(env: Mapping[str, str] = os.environ) -> PublisherSettings:
    raw = {field: env[var] for field, var in _ENV.items() if var in env}
    try:
        s = PublisherSettings.model_validate(raw)
    except ValidationError as e:
        bad = sorted({str(err["loc"][0]) for err in e.errors() if err.get("loc")})
        raise ConfigError(f"invalid or missing config: {', '.join(_ENV[b] for b in bad if b in _ENV)}") from None
    r, d = urlsplit(s.anchor_remote_url), urlsplit(s.database_url.get_secret_value())
    if d.hostname and (r.hostname, r.port) == (d.hostname, d.port or 5432):
        raise ConfigError("ANCHOR_REMOTE_URL points at the database server: the anchor must be a separate trust domain")
    return s


def build(cfg: PublisherSettings, event_hooks=None) -> tuple[HttpAnchor, KeyRegistry]:
    """Raises ValueError for an unreadable or malformed registry (a config error)."""
    registry = KeyRegistry.from_json(cfg.key_registry_path)
    return HttpAnchor(cfg.anchor_remote_url, cfg.anchor_remote_token.get_secret_value(),
                      cfg.anchor_remote_timeout_seconds, event_hooks), registry


def _load_state(path: str) -> dict | None:
    p = Path(path)
    if not p.exists():
        return None
    try:
        s = json.loads(p.read_text(encoding="utf-8"))
        if type(s["seq"]) is not int or not isinstance(s["head_hash"], str):
            raise TypeError
    except (ValueError, KeyError, TypeError, OSError):
        raise AnchorError("anchor state file is unreadable or malformed") from None
    return s


def _save_state(path: str, cp: dict) -> None:
    p = Path(path)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps({"seq": cp["payload"]["seq"], "head_hash": cp["payload"]["head_hash"]}), encoding="utf-8")
    os.replace(tmp, p)


def build_journal(cfg: PublisherSettings, event_hooks=None) -> HttpAnchor:
    """The journal stream's remote (ADR-034): the same service under `{ANCHOR_REMOTE_URL}/journal`, so its checkpoints
    live at /journal/checkpoints/{seq}, never next to the audit stream's /checkpoints/{seq}."""
    return HttpAnchor(cfg.anchor_remote_url.rstrip("/") + "/journal", cfg.anchor_remote_token.get_secret_value(),
                      cfg.anchor_remote_timeout_seconds, event_hooks)


# The two anchored streams, published in this order and never mixed: name -> (report prefix, checkpoint table, chain
# table, what to call the chain, state-file suffix). Each has its own remote path, state file and monitoring.
_STREAMS = {"audit": ("anchor-remote", "audit_checkpoints", "audit_log", "audit log", ""),
            "journal": ("anchor-remote[journal]", "execution_journal_checkpoints", "execution_journal",
                        "execution journal", ".journal")}


def _snapshot(database_url: str, seqs: list[int], registry: KeyRegistry, full: bool, stream: str = "audit"):
    """(checkpoints, top chain seq, {seq: entry_hash} for `seqs`) of one stream. The transaction is committed and the
    connection closed when this returns. # ponytail: reads every checkpoint; upgrade path is `WHERE seq > remote head`."""
    _, cp_table, log_table, _, _ = _STREAMS[stream]
    with psycopg.connect(database_url, connect_timeout=5) as conn:
        conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        conn.read_only = True
        if full:
            if stream == "audit":
                audit.verify(conn, registry.public_keys())
            else:
                journal.verify(conn, registry)
        cps = [{"payload": {"seq": r[0], "head_hash": r[1], "ts": r[2]}, "sig": r[3], "kid": r[4]} for r in
               conn.execute(f"SELECT seq, head_hash, ts, sig, kid FROM {cp_table} ORDER BY seq")]
        top = conn.execute(f"SELECT coalesce(max(seq), 0) FROM {log_table}").fetchone()[0]
        heads = dict(conn.execute(f"SELECT seq, entry_hash FROM {log_table} WHERE seq = ANY(%s::bigint[])",
                                  (seqs,)).fetchall())
    return cps, top, heads


def _problems(listed: list[dict], cps: list[dict], top: int, heads: dict, state: dict | None) -> list[str]:
    remote = {c["payload"]["seq"]: c["payload"]["head_hash"] for c in listed}
    local = {c["payload"]["seq"]: c["payload"]["head_hash"] for c in cps}
    rmax, out = max(remote, default=0), []
    if state is not None and remote.get(state["seq"]) != state["head_hash"]:
        out.append(f"remote rolled back: previously verified seq {state['seq']} is missing or changed")
    if rmax > top:
        out.append(f"database holds {top} entries but the remote anchor reached seq {rmax}: the local chain was "
                   "rewound (restored older, or its tail deleted)")
    for seq, head in remote.items():
        if seq > top:
            continue
        if heads.get(seq) != head or local.get(seq, head) != head:
            out.append(f"seq {seq}: conflicting head_hash, the remote does not match the local chain (history "
                       "rewritten, or a forged remote entry)")
        elif seq not in local:
            out.append(f"seq {seq}: the remote holds a checkpoint the database no longer has (local checkpoint deleted)")
    gaps = [s for s in local if s <= rmax and s not in remote]
    if gaps:
        out.append(f"remote is missing checkpoint seq {', '.join(map(str, gaps[:10]))}" +
                   (f" and {len(gaps) - 10} more" if len(gaps) > 10 else "") + " (gap)")
    return out


def _lag(backlog: list[dict], now: float, cfg: PublisherSettings) -> tuple[bool, str]:
    if not backlog:
        return False, "unpublished: none"
    age = int(now - backlog[0]["payload"]["ts"])
    span = f"seq {backlog[0]['payload']['seq']}..{backlog[-1]['payload']['seq']}"
    if age > cfg.anchor_max_lag_seconds:
        return True, f"LAG: unpublished {span}, oldest {age}s > ANCHOR_MAX_LAG_SECONDS={cfg.anchor_max_lag_seconds}"
    return False, f"unpublished {span}, oldest {age}s (within the {cfg.anchor_max_lag_seconds}s lag budget)"


def cycle(cfg: PublisherSettings, remote: HttpAnchor, registry: KeyRegistry, *, publish: bool,
          now: float | None = None, journal_remote: HttpAnchor | None = None) -> tuple[int, list[str]]:
    """One publish (publish=True) or check (False) pass over both streams, audit first, then the journal (each
    independent: a failing stream never stops the other). (worst exit code, report lines). Fails closed.
    `journal_remote`: the journal stream's remote (default: build_journal(cfg))."""
    now = time.time() if now is None else now
    code, lines = _stream_cycle(cfg, "audit", remote, registry, publish, now)
    jcode, jlines = _stream_cycle(cfg, "journal", journal_remote or build_journal(cfg), registry, publish, now)
    return max(code, jcode), lines + jlines


def _stream_cycle(cfg: PublisherSettings, stream: str, remote: HttpAnchor, registry: KeyRegistry, publish: bool,
                  now: float) -> tuple[int, list[str]]:
    p, _, _, label, suffix = _STREAMS[stream]
    url = cfg.database_url.get_secret_value()
    state_path = cfg.anchor_state_path + suffix
    try:
        state = _load_state(state_path)
        try:
            listed = [e["checkpoint"] for e in remote.entries(registry)]
        except RemoteUnavailable as e:
            if not publish:
                return 1, [f"{p}: FAILED: {e}; cannot verify"]
            cps, _, _ = _snapshot(url, [], registry, False, stream)
            floor = state["seq"] if state else 0
            late, line = _lag([c for c in cps if c["payload"]["seq"] > floor], now, cfg)
            return int(late), [f"{p}: WARN: {e}; nothing published", f"{p}: {line}"]
        cps, top, heads = _snapshot(url, [c["payload"]["seq"] for c in listed], registry, not publish, stream)
        problems = _problems(listed, cps, top, heads, state)
        if problems:
            return 1, [f"{p}: FAILED: {x}" for x in problems]
        rmax = listed[-1]["payload"]["seq"] if listed else 0
        backlog = [c for c in cps if c["payload"]["seq"] > rmax]
        head, done, lines = (listed[-1] if listed else None), [], []
        if publish:
            for c in backlog:
                try:
                    remote.publish(c, registry)
                except RemoteUnavailable as e:
                    lines.append(f"{p}: WARN: {e} at seq {c['payload']['seq']}; will resume there")
                    break
                head = c
                done.append(c["payload"]["seq"])
            backlog = backlog[len(done):]
        if head is not None:
            _save_state(state_path, head)
        late, lag_line = _lag(backlog, now, cfg)
        held = f"remote holds {len(listed) + len(done)} checkpoints through seq {head['payload']['seq']}, each " \
               "included in the local chain" if head else "remote holds no checkpoint"
        pub = f"; published seq {done[0]}..{done[-1]}" if done else ""
        lines.insert(0, f"{p}: OK: {held}{pub}; {lag_line}" if not late else f"{p}: {lag_line}")
        return int(late), lines
    except (AnchorError, audit.AuditFailure, journal.JournalFailure, OSError) as e:
        return 1, [f"{p}: FAILED: {e}"]
    except psycopg.Error as e:
        return 1, [f"{p}: FAILED: cannot read the {label} ({type(e).__name__})"]


def run(cfg: PublisherSettings, remote: HttpAnchor, registry: KeyRegistry, iterations: int | None = None,
        sleep=time.sleep, journal_remote: HttpAnchor | None = None) -> int:
    """The publisher loop. A failing cycle is reported and retried next interval; it never stops on its own."""
    i, code = 0, 0
    journal_remote = journal_remote or build_journal(cfg)
    while iterations is None or i < iterations:
        code, lines = cycle(cfg, remote, registry, publish=True, journal_remote=journal_remote)
        print("\n".join(lines), flush=True)
        i += 1
        if iterations is None or i < iterations:
            sleep(cfg.anchor_publish_interval_seconds)
    return code


def main(argv=None, env: Mapping[str, str] = os.environ) -> int:
    p = argparse.ArgumentParser(prog="python -m actionproof.anchor_publisher")
    p.add_argument("cmd", choices=("once", "check", "run"))
    args = p.parse_args(argv)
    try:
        cfg = load_settings(env)
        remote, registry = build(cfg)
        jremote = build_journal(cfg)
    except (ConfigError, ValueError) as e:
        print(f"anchor-remote: config error: {e}", file=sys.stderr)
        return 2
    try:
        if args.cmd == "run":
            return run(cfg, remote, registry, journal_remote=jremote)
        code, lines = cycle(cfg, remote, registry, publish=args.cmd == "once", journal_remote=jremote)
    except Exception as e:  # fail closed: anything unexpected is a failed cycle
        print(f"anchor-remote: FAILED ({type(e).__name__})")
        return 1
    print("\n".join(lines))
    return code


if __name__ == "__main__":
    sys.exit(main())
