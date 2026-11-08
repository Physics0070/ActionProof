"use client";
import { useId, useState } from "react";
import { ApiError, apiPost, type Schemas } from "@/lib/api";
import { REASON_MAX, REASON_MIN } from "@/lib/console-format";
import { MonoLabel } from "@/components/ui/MonoLabel";
import { Signal } from "@/components/ui/Signal";
import { ReasonList } from "./Parts";

type Choice = "approve" | "reject";
type Phase =
  | { step: "edit" }
  | { step: "confirm"; choice: Choice }
  | { step: "pending"; choice: Choice }
  | { step: "done"; out: Schemas["DecisionOut"] }
  | { step: "failed"; error: ApiError };

/** No optimistic UI: the outcome shown is whatever the commit returned. */
export function DecisionForm({ hash, onDecided }: { hash: string; onDecided: () => void }) {
  const [phase, setPhase] = useState<Phase>({ step: "edit" });
  const [reason, setReason] = useState("");
  const [touched, setTouched] = useState(false);
  const id = useId();
  const trimmed = reason.trim();
  const tooShort = trimmed.length < REASON_MIN;
  const busy = phase.step === "pending";

  function review(choice: Choice) {
    setTouched(true);
    if (!tooShort) setPhase({ step: "confirm", choice });
  }

  async function send(choice: Choice) {
    if (busy) return;
    setPhase({ step: "pending", choice });
    try {
      const out = await apiPost("/api/requests/{request_hash}/decision", { decision: choice, reason: trimmed }, { path: { request_hash: hash } });
      setPhase({ step: "done", out });
      onDecided();
    } catch (e) {
      setPhase({ step: "failed", error: e instanceof ApiError ? e : new ApiError(0, "network", "Cannot reach the console API.") });
    }
  }

  const lock = phase.step === "pending" || phase.step === "done";
  const choice = phase.step === "confirm" || phase.step === "pending" ? phase.choice : null;

  return (
    <section className="d-bar" aria-label="Decision">
      <h2 className="visually-hidden">Decide</h2>
      <div className="c-form d-form">
        <div className="c-field">
          <label htmlFor={`${id}-reason`}>
            Reason ({REASON_MIN}-{REASON_MAX} characters)
          </label>
          <textarea
            id={`${id}-reason`}
            rows={1}
            value={reason}
            maxLength={REASON_MAX}
            disabled={lock}
            required
            aria-invalid={touched && tooShort}
            aria-describedby={`${id}-hint`}
            onChange={(e) => {
              setReason(e.target.value);
              if (phase.step === "confirm") setPhase({ step: "edit" });
            }}
          />
          <p id={`${id}-hint`} className={touched && tooShort ? "c-formerror" : "t-muted"} role={touched && tooShort ? "alert" : undefined}>
            {touched && tooShort ? `Enter at least ${REASON_MIN} characters. ` : ""}
            {trimmed.length}/{REASON_MAX}
          </p>
        </div>

        {phase.step === "edit" || phase.step === "failed" ? (
          <div className="c-actions">
            <button type="button" className="button button-primary" onClick={() => review("approve")}>
              Approve…
            </button>
            <button type="button" className="button" onClick={() => review("reject")}>
              Reject…
            </button>
          </div>
        ) : null}

        {choice ? (
          <div className="c-confirm" role="group" aria-label="Confirm decision">
            <p>
              {choice === "approve"
                ? "Approving mints a one-use token and commits the write if every check still passes."
                : "Rejecting closes this request without executing it."}{" "}
              This cannot be undone.
            </p>
            <div className="c-actions">
              <button type="button" className="button button-primary" disabled={busy} onClick={() => void send(choice)}>
                {busy ? "Waiting for the gate…" : `Confirm ${choice}`}
              </button>
              <button type="button" className="button" disabled={busy} onClick={() => setPhase({ step: "edit" })}>
                Cancel
              </button>
            </div>
          </div>
        ) : null}

        <div role="status" aria-live="polite" className="c-outcome">
          {phase.step === "pending" ? <MonoLabel muted>Submitting to the gate; the outcome appears here.</MonoLabel> : null}
          {phase.step === "done" ? (
            <>
              <Signal
                state={phase.out.outcome === "EXECUTED" ? "ALLOW" : "DENY"}
                label={phase.out.outcome === "DENY" ? `DENY · status ${phase.out.status}` : phase.out.outcome}
              />
              {phase.out.reasons.length ? <ReasonList reasons={phase.out.reasons} state="DENY" /> : null}
              {phase.out.outcome === "DENY" ? (
                <button type="button" className="button" onClick={() => setPhase({ step: "edit" })}>
                  Back to decision
                </button>
              ) : null}
            </>
          ) : null}
        </div>
        {phase.step === "failed" ? (
          <div role="alert" className="c-outcome">
            <Signal state="DENY" label={phase.error.code} />
            <p>{phase.error.message}</p>
          </div>
        ) : null}
      </div>
    </section>
  );
}
