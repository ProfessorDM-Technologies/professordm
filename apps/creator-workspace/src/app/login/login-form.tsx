"use client";

import { useActionState } from "react";
import { signIn, type SignInState } from "@/lib/auth/actions";

export function LoginForm({ next, initialError }: { next: string; initialError: string | null }) {
  const initialState: SignInState = { error: initialError };
  const [state, formAction, pending] = useActionState(signIn, initialState);

  return (
    <form action={formAction} className="space-y-5" noValidate>
      <input type="hidden" name="next" value={next} />

      <div className="space-y-2">
        <label htmlFor="email" className="block font-medium">
          Email
        </label>
        <input
          id="email"
          name="email"
          type="email"
          autoComplete="email"
          required
          aria-invalid={state.error ? true : undefined}
          aria-describedby={state.error ? "login-error" : undefined}
          className="block w-full rounded-lg border border-pdm-border bg-white p-3 text-base"
        />
      </div>

      <div className="space-y-2">
        <label htmlFor="password" className="block font-medium">
          Password
        </label>
        <input
          id="password"
          name="password"
          type="password"
          autoComplete="current-password"
          required
          aria-invalid={state.error ? true : undefined}
          aria-describedby={state.error ? "login-error" : undefined}
          className="block w-full rounded-lg border border-pdm-border bg-white p-3 text-base"
        />
      </div>

      <div aria-live="polite">
        {state.error ? (
          <p id="login-error" className="text-sm font-medium text-red-700">
            {state.error}
          </p>
        ) : null}
      </div>

      <button
        type="submit"
        disabled={pending}
        className="w-full rounded-lg bg-pdm-accent px-4 py-3 font-semibold text-white hover:bg-pdm-accent-strong disabled:opacity-60"
      >
        {pending ? "Signing in…" : "Sign in"}
      </button>
    </form>
  );
}
