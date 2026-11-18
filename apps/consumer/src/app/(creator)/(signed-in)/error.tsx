"use client";

import Link from "next/link";

export default function SignedInError({ retry }: { error: Error & { digest?: string }; retry: () => void }) {
  return (
    <div role="alert" className="space-y-4 rounded-lg border border-flora-border bg-white p-4 sm:p-6">
      <h1 className="text-xl font-semibold">Something went wrong</h1>
      <p className="text-flora-muted">We couldn&apos;t load this page. Please try again in a moment.</p>
      <div className="flex flex-wrap items-center gap-4">
        <button
          type="button"
          onClick={() => retry()}
          className="min-h-11 rounded-lg bg-flora-accent px-4 py-2 font-semibold text-white hover:bg-flora-accent-strong"
        >
          Try again
        </button>
        <Link href="/" className="font-semibold text-flora-accent-strong underline underline-offset-4">
          Go to Home
        </Link>
      </div>
    </div>
  );
}
