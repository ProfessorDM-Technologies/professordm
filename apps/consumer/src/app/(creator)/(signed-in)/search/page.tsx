import type { Metadata } from "next";
import Link from "next/link";
import { EmptyState } from "@/components/empty-state";
import { EntryCard } from "@/components/entry-card";
import { PageSection } from "@/components/page-section";
import { SearchForm } from "@/components/search-form";
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
    <div className="space-y-8">
      <h1 className="text-3xl leading-tight font-extrabold sm:text-4xl">Search</h1>

      <SearchForm id="search-query" defaultValue={query} />

      <PageSection id="results" title={heading}>
        {results.length > 0 ? (
          <ul className="space-y-3">
            {results.map((entry) => (
              <li key={entry.id}>
                <EntryCard entry={entry} />
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState
            icon="question"
            title={query ? "No answers match your search yet." : "No answers have been published yet."}
            action={{ href: "/ask-expert", label: "Ask the Expert" }}
          >
            {query ? "Try fewer words, or ask Sweetlife Flora directly." : "Check back soon, or ask Sweetlife Flora directly."}
          </EmptyState>
        )}
      </PageSection>

      {results.length > 0 ? (
        <p>
          <Link href="/ask-expert" className="font-semibold text-pdm-accent-strong underline underline-offset-4">
            Need more specific advice? Ask the Expert
          </Link>
        </p>
      ) : null}
    </div>
  );
}
