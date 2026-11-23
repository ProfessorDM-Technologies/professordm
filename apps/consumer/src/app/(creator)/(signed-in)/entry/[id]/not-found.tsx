import Link from "next/link";

export default function EntryNotFound() {
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
      <h1 id="not-found-heading" className="mt-6 text-3xl font-extrabold sm:text-4xl">
        This answer isn&apos;t available
      </h1>
      <p className="mt-3 text-pdm-muted">It may have been removed, or the link may be wrong.</p>
      <div className="mt-8 flex flex-wrap justify-center gap-3">
        <Link
          href="/search"
          className="pdm-press inline-flex min-h-11 items-center rounded-full bg-pdm-accent px-5 font-semibold text-pdm-on-accent hover:bg-pdm-accent-strong"
        >
          Search answers
        </Link>
        <Link
          href="/ask-expert"
          className="pdm-press inline-flex min-h-11 items-center rounded-full border border-pdm-border bg-pdm-panel px-5 font-semibold text-pdm-ink hover:border-pdm-accent hover:bg-pdm-subtle"
        >
          Ask the Expert
        </Link>
      </div>
    </section>
  );
}
