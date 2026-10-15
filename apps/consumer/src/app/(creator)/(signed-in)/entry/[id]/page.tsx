import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { getPublishedEntry } from "@/lib/knowledge/queries";
import { entryTitle } from "@/lib/knowledge/search";

export async function generateMetadata({ params }: PageProps<"/entry/[id]">): Promise<Metadata> {
  const { id } = await params;
  const entry = await getPublishedEntry(id);
  return { title: entry ? entryTitle(entry) : "Answer" };
}

export default async function EntryPage({ params }: PageProps<"/entry/[id]">) {
  const { id } = await params;
  const entry = await getPublishedEntry(id);

  if (!entry) {
    notFound();
  }

  const paragraphs = (entry.content ?? "").split(/\n\s*\n/).filter((block) => block.trim());

  return (
    <article className="space-y-6">
      <p>
        <Link href="/search" className="text-sm font-medium text-flora-accent-strong underline underline-offset-4">
          Back to search
        </Link>
      </p>

      <header className="space-y-3">
        <h1 className="text-2xl font-semibold tracking-tight">{entryTitle(entry)}</h1>
        {entry.tags && entry.tags.length > 0 ? (
          <ul className="flex flex-wrap gap-2" aria-label="Topics">
            {entry.tags.map((tag) => (
              <li key={tag}>
                <Link
                  href={`/search?q=${encodeURIComponent(tag)}`}
                  className="inline-flex min-h-11 items-center rounded-full bg-flora-tint px-4 text-sm font-medium text-flora-accent-strong hover:underline"
                >
                  {tag}
                </Link>
              </li>
            ))}
          </ul>
        ) : null}
      </header>

      <section aria-labelledby="answer-heading" className="space-y-4 rounded-lg border border-flora-border bg-white p-4 sm:p-6">
        <h2 id="answer-heading" className="text-lg font-semibold">
          Sweetlife Flora&apos;s answer
        </h2>
        {paragraphs.map((paragraph, index) => (
          <p key={index} className="whitespace-pre-line leading-relaxed">
            {paragraph.trim()}
          </p>
        ))}
      </section>

      <p>
        <Link href="/ask-expert" className="font-semibold text-flora-accent-strong underline underline-offset-4">
          Need more specific advice? Ask the Expert
        </Link>
      </p>
    </article>
  );
}
