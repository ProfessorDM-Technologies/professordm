import Link from "next/link";
import { EmptyState } from "@/components/empty-state";
import { PageHeader, PageSection } from "@/components/page-section";
import { SearchForm } from "@/components/search-form";
import { getCurrentUser } from "@/lib/auth/session";
import { FREE_ANSWER_LIMIT, freeAnswersLeft } from "@/lib/knowledge/free-answers";
import { getFreeViewsUsed, getPublishedTags } from "@/lib/knowledge/queries";
import { popularTopics } from "@/lib/knowledge/search";

export default async function HomePage() {
  const user = await getCurrentUser();
  const [freeViewsUsed, tagRows] = await Promise.all([
    user ? getFreeViewsUsed(user.id) : Promise.resolve(0),
    getPublishedTags(),
  ]);
  const left = freeAnswersLeft(freeViewsUsed);
  const topics = popularTopics(tagRows);

  return (
    <div className="space-y-8">
      <PageHeader
        title="Plant care answers from Sweetlife Flora"
        description="Search answers to questions other plant owners have already asked."
      />

      <SearchForm id="home-search" />

      <PageSection id="trial" title="Free answers remaining">
        <p className="rounded-2xl border border-pdm-border bg-pdm-panel p-5">
          <span className="font-display text-3xl font-extrabold text-pdm-heading tabular-nums">{left}</span>{" "}
          <span className="text-pdm-muted">of {FREE_ANSWER_LIMIT} free answers left</span>
        </p>
      </PageSection>

      <PageSection id="topics" title="Popular topics">
        {topics.length > 0 ? (
          <ul className="flex flex-wrap gap-2">
            {topics.map((topic) => (
              <li key={topic}>
                <Link
                  href={`/search?q=${encodeURIComponent(topic)}`}
                  className="pdm-press inline-flex min-h-11 items-center rounded-full border border-pdm-border bg-pdm-panel px-4 text-sm font-semibold text-pdm-ink hover:border-pdm-accent hover:bg-pdm-subtle"
                >
                  {topic}
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState icon="list" tone="teal" title="No topics yet" />
        )}
      </PageSection>

      <section
        aria-labelledby="ask-heading"
        className="flex items-start gap-4 rounded-2xl border border-pdm-border bg-pdm-panel p-5"
      >
        <span
          aria-hidden="true"
          className="grid size-12 shrink-0 place-items-center rounded-2xl rounded-bl-md bg-pdm-cyan-tint text-pdm-cyan-ink"
        >
          <svg viewBox="0 0 24 24" className="size-6" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
            <path d="M5 5h14v10h-7l-5 4v-4H5V5Zm5.2 3.3a1.9 1.9 0 1 1 2.6 1.8c-.5.2-.8.6-.8 1.1M12 13.2h.01" />
          </svg>
        </span>
        <div className="min-w-0 space-y-1 pt-0.5">
          <h2 id="ask-heading" className="text-lg font-bold">
            Can&apos;t find what you need?
          </h2>
          <p className="text-sm text-pdm-muted">Ask Sweetlife Flora directly for a personal answer.</p>
          <Link
            href="/ask-expert"
            className="pdm-press mt-2 inline-flex min-h-11 items-center rounded-full bg-pdm-accent px-5 font-semibold text-pdm-on-accent hover:bg-pdm-accent-strong"
          >
            Ask the Expert
          </Link>
        </div>
      </section>
    </div>
  );
}
