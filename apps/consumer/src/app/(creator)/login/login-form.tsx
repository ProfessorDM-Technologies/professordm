"use client";

import { useActionState } from "react";
import { signIn, type SignInState } from "@/lib/auth/actions";

const initialState: SignInState = { error: null };

export function LoginForm({ next }: { next: string }) {
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
          className="block w-full rounded-xl border border-pdm-border bg-pdm-panel p-3 text-base transition-colors focus:border-pdm-accent"
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
          className="block w-full rounded-xl border border-pdm-border bg-pdm-panel p-3 text-base transition-colors focus:border-pdm-accent"
        />
      </div>

      <div aria-live="polite">
        {state.error ? (
          <p id="login-error" className="text-sm font-medium text-pdm-danger-ink">
            {state.error}
          </p>
        ) : null}
      </div>

      <button
        type="submit"
        disabled={pending}
        className="pdm-press w-full rounded-full bg-pdm-accent px-4 py-3 font-semibold text-pdm-on-accent hover:bg-pdm-accent-strong disabled:opacity-60"
      >
        {pending ? "Signing in…" : "Sign in"}
      </button>
    </form>
  );
}
