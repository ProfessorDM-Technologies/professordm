import Link from "next/link";
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
        <p className="rounded-lg border border-flora-border bg-white p-4">
          <span className="text-2xl font-semibold text-flora-accent-strong">{left}</span>{" "}
          <span className="text-flora-muted">
            of {FREE_ANSWER_LIMIT} free answers left
          </span>
        </p>
      </section>

      <section aria-labelledby="topics-heading" className="space-y-2">
        <h2 id="topics-heading" className="text-lg font-semibold">
          Popular topics
        </h2>
        {topics.length > 0 ? (
          <ul className="flex flex-wrap gap-2">
            {topics.map((topic) => (
              <li key={topic}>
                <Link
                  href={`/search?q=${encodeURIComponent(topic)}`}
                  className="inline-flex min-h-11 items-center rounded-full border border-flora-border bg-white px-4 text-sm font-medium text-flora-accent-strong hover:bg-flora-tint"
                >
                  {topic}
                </Link>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-flora-muted">No topics yet.</p>
        )}
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
