import type { Metadata } from "next";
import Link from "next/link";
import { Placeholder } from "@/components/placeholder";

export const metadata: Metadata = {
  title: "Search",
};

export default async function SearchPage({ searchParams }: PageProps<"/search">) {
  const { q } = await searchParams;
  const query = typeof q === "string" ? q.trim() : "";

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
          {query ? `Results for “${query}”` : "Results"}
        </h2>
        <Placeholder>Matching answers will appear here.</Placeholder>
      </section>

      <p>
        <Link href="/ask-expert" className="font-semibold text-flora-accent-strong underline underline-offset-4">
          Need more specific advice? Ask the Expert
        </Link>
      </p>
    </div>
  );
}
