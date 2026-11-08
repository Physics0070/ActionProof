"use client";
// Minimal fetch hook: keeps the last good data while a reload runs, no setState in the effect body.
import { useCallback, useEffect, useState } from "react";
import { ApiError } from "./api";
import { useAuth } from "./console-auth";

type Res<T> = { fn: unknown; tick: number; data?: T; error?: ApiError };

export function useAsync<T>(fn: (signal: AbortSignal) => Promise<T>) {
  const { expire } = useAuth();
  const [res, setRes] = useState<Res<T> | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    const ctl = new AbortController();
    fn(ctl.signal)
      .then((data) => setRes({ fn, tick, data }))
      .catch((e: unknown) => {
        if (ctl.signal.aborted) return;
        const error = e instanceof ApiError ? e : new ApiError(0, "network", "Cannot reach the console API.");
        if (error.status === 401) expire();
        setRes((prev) => ({ fn, tick, data: prev?.data, error }));
      });
    return () => ctl.abort();
  }, [fn, tick, expire]);

  const reload = useCallback(() => setTick((t) => t + 1), []);
  const loading = !res || res.fn !== fn || res.tick !== tick;
  return { data: res?.data, error: loading ? undefined : res?.error, loading, reload };
}
