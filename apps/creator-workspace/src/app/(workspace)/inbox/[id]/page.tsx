import type { Metadata } from "next";
import Link from "next/link";
import { PageSection } from "@/components/page-section";
import { Placeholder } from "@/components/placeholder";

export const metadata: Metadata = {
  title: "Question",
};

const ACTIONS = ["Save draft", "Decline", "Submit answer"] as const;

export default function QuestionPage() {
  return (
    <article className="space-y-6">
      <p>
        <Link href="/inbox" className="text-sm font-medium text-pdm-accent-strong underline underline-offset-4">
          Back to inbox
        </Link>
      </p>

      <h1 className="text-2xl font-semibold tracking-tight">Question</h1>

      <PageSection id="question" title="Question">
        <Placeholder>The follower&apos;s question, source and photos will appear here.</Placeholder>
      </PageSection>

      <PageSection id="clarification" title="Clarification history">
        <Placeholder>Clarification prompts and replies will appear here.</Placeholder>
      </PageSection>

      <PageSection id="classification" title="Classification and safety">
        <Placeholder>The AI label, confidence and any safety flags will appear here.</Placeholder>
      </PageSection>

      <PageSection id="draft" title="AI draft">
        <Placeholder>The AI draft will appear here with its sources labelled creator knowledge or web.</Placeholder>
      </PageSection>

      <PageSection id="answer" title="Your answer">
        <Placeholder>
          Rewrite the draft in your own voice and add at least one tag. An unchanged draft can&apos;t be sent.
        </Placeholder>
        <div className="flex flex-col gap-2 sm:flex-row">
          {ACTIONS.map((label) => (
            <button
              key={label}
              type="button"
              disabled
              aria-describedby="actions-note"
              className="rounded-lg border border-pdm-border bg-white px-4 py-3 font-medium disabled:cursor-not-allowed disabled:opacity-60"
            >
              {label}
            </button>
          ))}
        </div>
        <p id="actions-note" className="text-sm text-pdm-muted">
          These actions are not available yet.
        </p>
      </PageSection>
    </article>
  );
}
