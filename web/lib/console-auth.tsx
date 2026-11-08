"use client";
// Session state for the console. The session itself is the httpOnly `ap_session` cookie set by the backend; this
// only mirrors `GET /api/auth/me` so the UI can show the right navigation. Authority is always the server's (403s).
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { ApiError, apiGet, apiPost, type Schemas } from "./api";

export type User = Schemas["Me"];
export type AuthState =
  | { status: "loading" }
  | { status: "anon" }
  | { status: "error"; error: ApiError }
  | { status: "in"; user: User };

type Ctx = {
  state: AuthState;
  signedIn: (user: User) => void;
  signOut: () => Promise<void>;
  /** A data call came back 401: the session is gone. */
  expire: () => void;
  retry: () => void;
};

const AuthContext = createContext<Ctx | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: "loading" });
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const ctl = new AbortController();
    apiGet("/api/auth/me", { signal: ctl.signal })
      .then((user) => setState({ status: "in", user }))
      .catch((e: unknown) => {
        if (ctl.signal.aborted) return;
        if (e instanceof ApiError && e.status === 401) setState({ status: "anon" });
        else setState({ status: "error", error: e instanceof ApiError ? e : new ApiError(0, "network", "Cannot reach the console API.") });
      });
    return () => ctl.abort();
  }, [tick]);

  const signedIn = useCallback((user: User) => setState({ status: "in", user }), []);
  const expire = useCallback(() => setState({ status: "anon" }), []);
  const retry = useCallback(() => {
    setState({ status: "loading" });
    setTick((t) => t + 1);
  }, []);
  const signOut = useCallback(async () => {
    try {
      await apiPost("/api/auth/logout", undefined);
    } catch {
      // Even if the call failed, the next /me decides; do not pretend the server forgot us.
      setState({ status: "loading" });
      setTick((t) => t + 1);
      return;
    }
    setState({ status: "anon" });
  }, []);

  const value = useMemo(() => ({ state, signedIn, signOut, expire, retry }), [state, signedIn, signOut, expire, retry]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): Ctx {
  const c = useContext(AuthContext);
  if (!c) throw new Error("useAuth outside AuthProvider");
  return c;
}

export const canRead = (u: User) => u.roles.includes("reviewer") || u.roles.includes("admin");
export const canDecide = (u: User) => u.roles.includes("reviewer"); // admin cannot decide (ADR-008)
