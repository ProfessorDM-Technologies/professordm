import type { Metadata } from "next";
import Link from "next/link";
import { Placeholder } from "@/components/placeholder";

export const metadata: Metadata = {
  title: "Answer",
};

export default function EntryPage() {
  return (
    <article className="space-y-6">
      <p>
        <Link href="/search" className="text-sm font-medium text-flora-accent-strong underline underline-offset-4">
          Back to search
        </Link>
      </p>

      <h1 className="text-2xl font-semibold tracking-tight">Answer</h1>

      <section aria-labelledby="question-heading" className="space-y-2">
        <h2 id="question-heading" className="text-lg font-semibold">
          Question
        </h2>
        <Placeholder>The question will appear here.</Placeholder>
      </section>

      <section aria-labelledby="answer-heading" className="space-y-2">
        <h2 id="answer-heading" className="text-lg font-semibold">
          Sweetlife Flora&apos;s answer
        </h2>
        <Placeholder>The full answer will appear here.</Placeholder>
      </section>

      <p>
        <Link href="/ask-expert" className="font-semibold text-flora-accent-strong underline underline-offset-4">
          Need more specific advice? Ask the Expert
        </Link>
      </p>
    </article>
  );
}
