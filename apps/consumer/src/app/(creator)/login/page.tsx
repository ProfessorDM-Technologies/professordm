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
      <div className="space-y-2 pb-8 text-center">
        <p className="text-sm font-semibold uppercase tracking-wide text-flora-accent">Ask Sweetlife Flora</p>
        <h1 className="text-2xl font-semibold tracking-tight">Sign in to access verified plant care answers</h1>
        <p className="text-flora-muted">No payment needed until you subscribe or ask an expert.</p>
      </div>
      <LoginForm next={safeNextPath(next)} />
    </main>
  );
}
