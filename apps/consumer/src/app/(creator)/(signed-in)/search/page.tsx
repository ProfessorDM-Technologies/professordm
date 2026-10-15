import type { Metadata } from "next";
import Link from "next/link";
import { EntryCard } from "@/components/entry-card";
import { getPublishedEntries } from "@/lib/knowledge/queries";
import { filterEntries } from "@/lib/knowledge/search";

export const metadata: Metadata = {
  title: "Search",
};

export default async function SearchPage({ searchParams }: PageProps<"/search">) {
  const { q } = await searchParams;
  const query = typeof q === "string" ? q.trim().slice(0, 200) : "";
  const results = filterEntries(await getPublishedEntries(), query);
  const heading = query
    ? `${results.length} ${results.length === 1 ? "result" : "results"} for “${query}”`
    : "All answers";

  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Search</h1>

      <form action="/search" role="search" className="flex gap-2">
        <label htmlFor="search-query" className="sr-only">
          Search plant care answers
        </label>
        <input
          id="search-query"
          name="q"
          type="search"
          defaultValue={query}
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

      <section aria-labelledby="results-heading" className="space-y-2">
        <h2 id="results-heading" className="text-lg font-semibold">
          {heading}
        </h2>
        {results.length > 0 ? (
          <ul className="space-y-3">
            {results.map((entry) => (
              <li key={entry.id}>
                <EntryCard entry={entry} />
              </li>
            ))}
          </ul>
        ) : (
          <div className="space-y-2 rounded-lg border border-flora-border bg-white p-4">
            <p className="font-medium">No answers match your search yet.</p>
            <p className="text-flora-muted">Try fewer words, or ask Sweetlife Flora directly.</p>
            <Link
              href="/ask-expert"
              className="inline-block font-semibold text-flora-accent-strong underline underline-offset-4"
            >
              Ask the Expert
            </Link>
          </div>
        )}
      </section>

      {results.length > 0 ? (
        <p>
          <Link href="/ask-expert" className="font-semibold text-flora-accent-strong underline underline-offset-4">
            Need more specific advice? Ask the Expert
          </Link>
        </p>
      ) : null}
    </div>
  );
}
