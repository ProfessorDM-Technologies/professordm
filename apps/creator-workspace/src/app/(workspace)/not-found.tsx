import Link from "next/link";

// 404 inside the workspace shell, so the logo, nav and account menu stay put and the way back is one tap away.
export default function WorkspaceNotFound() {
  return (
    <section aria-labelledby="not-found-heading" className="mx-auto flex max-w-md flex-col items-center py-12 text-center">
      <span
        aria-hidden="true"
        className="grid size-16 place-items-center rounded-3xl rounded-bl-lg bg-pdm-cyan-tint text-pdm-cyan-ink"
      >
        <svg viewBox="0 0 24 24" className="size-8" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
          <path d="M5 5h14v10h-7l-5 4v-4H5V5Zm5.2 3.3a1.9 1.9 0 1 1 2.6 1.8c-.5.2-.8.6-.8 1.1M12 13.2h.01" />
        </svg>
      </span>
      <p className="mt-6 font-display text-sm font-bold tracking-widest text-pdm-muted">404</p>
      <h1 id="not-found-heading" className="mt-1 text-3xl font-extrabold sm:text-4xl">
        Page not found
      </h1>
      <p className="mt-3 text-pdm-muted">
        This page doesn&apos;t exist or isn&apos;t yours to see. The link may be old, or the conversation may have been removed.
      </p>
      <div className="mt-8 flex flex-wrap justify-center gap-3">
        <Link
          href="/inbox"
          className="pdm-press inline-flex min-h-11 items-center rounded-full bg-pdm-accent px-5 font-semibold text-pdm-on-accent hover:bg-pdm-accent-strong"
        >
          Open Inbox
        </Link>
        <Link
          href="/"
          className="pdm-press inline-flex min-h-11 items-center rounded-full border border-pdm-border bg-pdm-panel px-5 font-semibold text-pdm-ink hover:border-pdm-accent hover:bg-pdm-subtle"
        >
          Go to Bank
        </Link>
      </div>
    </section>
  );
}
