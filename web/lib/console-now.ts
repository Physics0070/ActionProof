"use client";
import { useEffect, useState } from "react";

/** Wall clock for relative ages. null until mounted (server and first client render agree). */
export function useNow(intervalMs = 30000): number | null {
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    const first = setTimeout(() => setNow(Date.now()), 0);
    const id = setInterval(() => setNow(Date.now()), intervalMs);
    return () => {
      clearTimeout(first);
      clearInterval(id);
    };
  }, [intervalMs]);
  return now;
}
