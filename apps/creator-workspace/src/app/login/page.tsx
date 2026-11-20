import type { Metadata } from "next";
import { safeNextPath } from "@/lib/routes";
import { LoginForm } from "./login-form";

export const metadata: Metadata = {
  title: "Sign in",
  alternates: { canonical: "/login" },
};

const ERROR_MESSAGES: Record<string, string> = {
  forbidden: "This account doesn't have access to the Creator Workspace.",
};

export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  const { next, error } = await searchParams;
  const initialError = typeof error === "string" ? (ERROR_MESSAGES[error] ?? null) : null;

  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-md flex-col justify-center px-4 py-10">
      <div className="flex flex-col items-center gap-3 pb-8 text-center">
        {/* eslint-disable-next-line @next/next/no-img-element -- static brand asset */}
        <img src="/brand/mark.webp" alt="" width={278} height={192} className="h-20 w-auto" />
        {/* eslint-disable-next-line @next/next/no-img-element -- static brand asset */}
        <img src="/brand/wordmark-light.svg" alt="ProfessorDM" width={530} height={96} className="h-7 w-auto dark:hidden" />
        {/* eslint-disable-next-line @next/next/no-img-element -- static brand asset */}
        <img src="/brand/wordmark-dark.svg" alt="ProfessorDM" width={530} height={96} className="hidden h-7 w-auto dark:block" />
        <h1 className="pt-4 text-2xl font-bold">Sign in to your Creator Workspace</h1>
        <p className="text-pdm-muted">Creator accounts are invite-only.</p>
      </div>
      <div className="rounded-2xl border border-pdm-border bg-pdm-panel p-6 shadow-pdm">
        <LoginForm next={safeNextPath(next)} initialError={initialError} />
      </div>
    </main>
  );
}
