import Link from "next/link";
import { Placeholder } from "@/components/placeholder";

export default function HomePage() {
  return (
    <div className="space-y-8">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">Plant care answers from Sweetlife Flora</h1>
        <p className="text-flora-muted">Search answers to questions other plant owners have already asked.</p>
      </div>

      <form action="/search" role="search" className="flex gap-2">
        <label htmlFor="home-search" className="sr-only">
          Search plant care answers
        </label>
        <input
          id="home-search"
          name="q"
          type="search"
          placeholder="Search plant care answers"
          className="min-w-0 flex-1 rounded-lg border border-flora-border bg-white p-3 text-base"
        />
        <button
          type="submit"
          className="rounded-lg bg-flora-accent px-4 py-3 font-semibold text-white hover:bg-flora-accent-strong"
        >
          Search
        </button>
      </form>

      <section aria-labelledby="trial-heading" className="space-y-2">
        <h2 id="trial-heading" className="text-lg font-semibold">
          Free answers remaining
        </h2>
        <Placeholder>Your free answer count will appear here.</Placeholder>
      </section>

      <section aria-labelledby="topics-heading" className="space-y-2">
        <h2 id="topics-heading" className="text-lg font-semibold">
          Popular topics
        </h2>
        <Placeholder>Popular topics will appear here.</Placeholder>
      </section>

      <section aria-labelledby="ask-heading" className="space-y-2 rounded-lg bg-flora-tint p-4">
        <h2 id="ask-heading" className="text-lg font-semibold">
          Can&apos;t find what you need?
        </h2>
        <p className="text-flora-muted">Ask Sweetlife Flora directly for a personal answer.</p>
        <Link href="/ask-expert" className="inline-block font-semibold text-flora-accent-strong underline underline-offset-4">
          Ask the Expert
        </Link>
      </section>
    </div>
  );
}
