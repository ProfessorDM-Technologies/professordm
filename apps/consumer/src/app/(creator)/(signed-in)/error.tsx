"use client";

import Link from "next/link";

export default function SignedInError({ retry }: { error: Error & { digest?: string }; retry: () => void }) {
  return (
    <section role="alert" className="mx-auto flex max-w-md flex-col items-center py-12 text-center">
      <span
        aria-hidden="true"
        className="grid size-16 place-items-center rounded-3xl rounded-bl-lg bg-pdm-danger-bg text-pdm-danger-ink"
      >
        <svg viewBox="0 0 24 24" className="size-8" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
          <path d="M5 5h14v10h-7l-5 4v-4H5V5Zm7 2.5v3.5m0 2.5h.01" />
        </svg>
      </span>
      <h1 className="mt-6 text-3xl font-extrabold sm:text-4xl">Something went wrong</h1>
      <p className="mt-3 text-pdm-muted">We couldn&apos;t load this page. Please try again in a moment.</p>
      <div className="mt-8 flex flex-wrap justify-center gap-3">
        <button
          type="button"
          onClick={() => retry()}
          className="pdm-press inline-flex min-h-11 items-center rounded-full bg-pdm-accent px-5 font-semibold text-pdm-on-accent hover:bg-pdm-accent-strong"
        >
          Try again
        </button>
        <Link
          href="/"
          className="pdm-press inline-flex min-h-11 items-center rounded-full border border-pdm-border bg-pdm-panel px-5 font-semibold text-pdm-ink hover:border-pdm-accent hover:bg-pdm-subtle"
        >
          Go to Home
        </Link>
      </div>
    </section>
  );
}
