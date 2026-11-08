"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, type ReactNode } from "react";
import { MonoLabel } from "@/components/ui/MonoLabel";
import { AuthProvider, canRead, useAuth } from "@/lib/console-auth";
import { ErrorState, Loading } from "./Parts";
import "./console.css";

const LOGIN = "/console/login";

function Gate({ children }: { children: ReactNode }) {
  const { state, retry } = useAuth();
  const path = usePathname();
  const router = useRouter();
  const onLogin = path === LOGIN;

  useEffect(() => {
    if (state.status === "anon" && !onLogin) router.replace(LOGIN);
    if (state.status === "in" && onLogin) router.replace("/console");
  }, [state.status, onLogin, router]);

  if (state.status === "loading") return <Loading what="session" />;
  if (state.status === "error") return <ErrorState error={state.error} onRetry={retry} />;
  if (state.status === "anon" && !onLogin) return <Loading what="sign-in" />;
  if (state.status === "in" && onLogin) return <Loading what="console" />;
  return <>{children}</>;
}

function Nav() {
  const { state, signOut } = useAuth();
  const path = usePathname();
  const user = state.status === "in" ? state.user : null;
  const link = (href: string, label: string) => (
    <Link href={href} aria-current={path === href ? "page" : undefined} className="c-navlink">
      <MonoLabel>{label}</MonoLabel>
    </Link>
  );
  return (
    <header className="band-carbon">
      <nav aria-label="Console" className="container c-nav">
        <Link href="/" className="c-brand">
          <MonoLabel>ActionProof</MonoLabel>
        </Link>
        {user && canRead(user) ? (
          <>
            {link("/console", "Queue")}
            {link("/console/audit", "Audit")}
          </>
        ) : null}
        {user ? (
          <span className="c-who">
            <MonoLabel muted>
              {user.login} · {user.roles.join(", ") || "no role"}
            </MonoLabel>
            <button type="button" className="button" onClick={() => void signOut()}>
              Sign out
            </button>
          </span>
        ) : null}
      </nav>
    </header>
  );
}

export function ConsoleShell({ children }: { children: ReactNode }) {
  return (
    <AuthProvider>
      <Nav />
      <main id="main" className="container c-main">
        <Gate>{children}</Gate>
      </main>
    </AuthProvider>
  );
}
