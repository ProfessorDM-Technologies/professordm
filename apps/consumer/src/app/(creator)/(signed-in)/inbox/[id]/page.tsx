import type { Metadata } from "next";
import Link from "next/link";
import { Placeholder } from "@/components/placeholder";

export const metadata: Metadata = {
  title: "Your Answer",
};

const ACTIONS = ["Send Follow-up", "Accept answer", "Request Refund"] as const;

export default function InboxAnswerPage() {
  return (
    <article className="space-y-6">
      <p>
        <Link href="/inbox" className="text-sm font-medium text-flora-accent-strong underline underline-offset-4">
          Back to inbox
        </Link>
      </p>

      <h1 className="text-2xl font-semibold tracking-tight">Your answer</h1>

      <section aria-labelledby="status-heading" className="space-y-2">
        <h2 id="status-heading" className="text-lg font-semibold">
          Status
        </h2>
        <Placeholder>Question status and dates will appear here.</Placeholder>
      </section>

      <section aria-labelledby="question-heading" className="space-y-2">
        <h2 id="question-heading" className="text-lg font-semibold">
          Your question
        </h2>
        <Placeholder>Your question will appear here.</Placeholder>
      </section>

      <section aria-labelledby="answer-heading" className="space-y-2">
        <h2 id="answer-heading" className="text-lg font-semibold">
          Answer
        </h2>
        <Placeholder>The answer will appear here.</Placeholder>
      </section>

      <section aria-labelledby="actions-heading" className="space-y-3">
        <h2 id="actions-heading" className="text-lg font-semibold">
          What would you like to do?
        </h2>
        <div className="flex flex-col gap-2 sm:flex-row">
          {ACTIONS.map((label) => (
            <button
              key={label}
              type="button"
              disabled
              aria-describedby="actions-note"
              className="rounded-lg border border-flora-border bg-white px-4 py-3 font-medium disabled:cursor-not-allowed disabled:opacity-60"
            >
              {label}
            </button>
          ))}
        </div>
        <p id="actions-note" className="text-sm text-flora-muted">
          These actions are not available yet.
        </p>
      </section>
    </article>
  );
}
