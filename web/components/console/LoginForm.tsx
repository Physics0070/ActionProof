"use client";
import { useRef, useState, type FormEvent } from "react";
import { ApiError, apiPost } from "@/lib/api";
import { useAuth } from "@/lib/console-auth";
import { Card } from "@/components/ui/Card";
import { Signal } from "@/components/ui/Signal";

export function LoginForm() {
  const { signedIn } = useAuth();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const pw = useRef<HTMLInputElement>(null);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (busy) return;
    const f = new FormData(e.currentTarget);
    setBusy(true);
    setError(null);
    try {
      const out = await apiPost("/api/auth/login", { login: String(f.get("login") ?? ""), password: String(f.get("password") ?? "") });
      signedIn({ login: out.login, roles: out.roles });
    } catch (err) {
      if (pw.current) pw.current.value = "";
      // One generic message for any bad credential; never echo what was typed.
      if (err instanceof ApiError && err.status === 429) setError("Too many failed attempts. Try again later.");
      else if (err instanceof ApiError && err.status === 401) setError("Invalid login or password.");
      else setError("Sign-in is unavailable right now. Try again.");
      setBusy(false);
    }
  }

  return (
    <div className="c-login">
      <h1 className="t-h3">Sign in to the review console</h1>
      <Card>
        {/* method=post: if the form is submitted before hydration the password never lands in the URL */}
        <form method="post" onSubmit={submit} className="c-form" aria-busy={busy}>
          <div className="c-field">
            <label htmlFor="login">Login</label>
            <input id="login" name="login" type="text" autoComplete="username" required maxLength={64} autoCapitalize="none" spellCheck={false} />
          </div>
          <div className="c-field">
            <label htmlFor="password">Password</label>
            <input id="password" name="password" ref={pw} type="password" autoComplete="current-password" required maxLength={256} />
          </div>
          <div role="alert" className="c-formerror">
            {error ? <Signal state="DENY" label={error} /> : null}
          </div>
          <button type="submit" className="button button-primary" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </Card>
    </div>
  );
}
