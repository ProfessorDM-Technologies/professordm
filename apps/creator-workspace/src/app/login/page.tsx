import type { Metadata } from "next";
import { safeNextPath } from "@/lib/routes";
import { LoginForm } from "./login-form";

export const metadata: Metadata = {
  title: "Sign in",
};

const ERROR_MESSAGES: Record<string, string> = {
  forbidden: "This account doesn't have access to the Creator Workspace.",
};

export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  const { next, error } = await searchParams;
  const initialError = typeof error === "string" ? (ERROR_MESSAGES[error] ?? null) : null;

  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-md flex-col justify-center px-4 py-10">
      <div className="space-y-2 pb-8 text-center">
        <p className="text-sm font-semibold uppercase tracking-wide text-pdm-accent">ProfessorDM</p>
        <h1 className="text-2xl font-semibold tracking-tight">Sign in to your Creator Workspace</h1>
        <p className="text-pdm-muted">Creator accounts are invite-only.</p>
      </div>
      <div className="rounded-xl border border-pdm-border bg-white p-6 shadow-sm">
        <LoginForm next={safeNextPath(next)} initialError={initialError} />
      </div>
    </main>
  );
}
