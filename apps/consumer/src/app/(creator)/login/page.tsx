import type { Metadata } from "next";
import { safeNextPath } from "@/lib/routes";
import { LoginForm } from "./login-form";

export const metadata: Metadata = {
  title: "Sign in",
};

export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  const { next } = await searchParams;

  return (
    <main className="mx-auto flex min-h-dvh w-full max-w-md flex-col justify-center px-4 py-10">
      <div className="flex flex-col items-center gap-3 pb-8 text-center">
        {/* eslint-disable-next-line @next/next/no-img-element -- static brand asset */}
        <img src="/brand/mark.webp" alt="" width={278} height={192} className="h-20 w-auto" />
        {/* eslint-disable-next-line @next/next/no-img-element -- static brand asset */}
        <img src="/brand/wordmark-light.svg" alt="ProfessorDM" width={530} height={96} className="h-7 w-auto dark:hidden" />
        {/* eslint-disable-next-line @next/next/no-img-element -- static brand asset */}
        <img src="/brand/wordmark-dark.svg" alt="ProfessorDM" width={530} height={96} className="hidden h-7 w-auto dark:block" />
        <h1 className="pt-4 text-2xl font-bold">Sign in to Ask Sweetlife Flora</h1>
        <p className="text-pdm-muted">No payment needed until you subscribe or ask an expert.</p>
      </div>
      <div className="rounded-2xl border border-pdm-border bg-pdm-panel p-6 shadow-pdm">
        <LoginForm next={safeNextPath(next)} />
      </div>
    </main>
  );
}
