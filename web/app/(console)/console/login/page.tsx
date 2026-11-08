import type { Metadata } from "next";
import { LoginForm } from "@/components/console/LoginForm";

export const metadata: Metadata = { title: "Sign in", description: "Sign in to review the actions an AI agent paused.", alternates: { canonical: "/console/login" } };

export default function LoginPage() {
  return <LoginForm />;
}
