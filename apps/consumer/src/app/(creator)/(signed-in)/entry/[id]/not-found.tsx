import Link from "next/link";

export default function EntryNotFound() {
  return (
    <div className="space-y-4 rounded-lg border border-flora-border bg-white p-4 sm:p-6">
      <h1 className="text-xl font-semibold">This answer isn&apos;t available</h1>
      <p className="text-flora-muted">It may have been removed, or the link may be wrong.</p>
      <div className="flex flex-wrap items-center gap-4">
        <Link
          href="/search"
          className="inline-flex min-h-11 items-center rounded-lg bg-flora-accent px-4 font-semibold text-white hover:bg-flora-accent-strong"
        >
          Search answers
        </Link>
        <Link href="/ask-expert" className="font-semibold text-flora-accent-strong underline underline-offset-4">
          Ask the Expert
        </Link>
      </div>
    </div>
  );
}
