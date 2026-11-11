import type { Metadata } from "next";
import { cardLinkClass } from "@/components/ui/card-styles";
import { Page } from "@/components/page";
import Link from "next/link";
import { RealtimeRefresh } from "@/components/inbox/realtime-refresh";
import { LocalTime } from "@/components/local-time";
import { PageHeader, PageSection } from "@/components/page-section";
import { Placeholder } from "@/components/placeholder";
import { QueueTabs } from "@/components/queue-tabs";
import { changeRatio } from "@/lib/inbox/answer";
import { listQuestions, type QueueQuestion } from "@/lib/inbox/questions";

export const metadata: Metadata = {
  title: "Sent",
};

// One delivered answer (spec section 8.4). Opens the question with its context and sources.
function SentCard({ question }: { question: QueueQuestion }) {
  const username = question.follower?.username ? `@${question.follower.username}` : "Unknown sender";
  const answer = question.draft?.finalText ?? null;
  const aiText = question.draft?.aiText ?? null;
  const edits = aiText && answer ? Math.round(changeRatio(aiText, answer) * 100) : null;

  return (
    <li>
      <Link
        href={`/inbox/question/${question.id}`}
        className={cardLinkClass()}
      >
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
          <p className="font-semibold">{username}</p>
          {question.deliveredAt ? (
            <p className="text-xs text-pdm-muted">
              Sent <LocalTime value={question.deliveredAt} />
            </p>
          ) : null}
        </div>

        <p className="line-clamp-1 text-sm text-pdm-muted">{question.questionText}</p>
        <p className="line-clamp-2 text-sm text-pdm-ink">
          <span className="sr-only">Your answer: </span>
          {answer || "(Answer text not available)"}
        </p>

        <div className="flex flex-wrap items-center gap-2 text-xs">
          {edits !== null ? <span className="text-pdm-muted">Your edits: {edits}%</span> : null}
          {question.tags.map((tag) => (
            <span key={tag} className="rounded-full bg-pdm-primary-tint px-2 py-0.5 font-semibold text-pdm-primary">
              {tag}
            </span>
          ))}
        </div>
      </Link>
    </li>
  );
}

export default async function SentPage() {
  const { questions, error } = await listQuestions("sent");

  return (
    <Page className="space-y-6">
      <RealtimeRefresh />
      <PageHeader title="Sent" description="Answers you've sent, newest first." />
      <QueueTabs current="/sent" />

      <PageSection id="sent" title="Sent answers">
        {error ? (
          <p role="alert" className="rounded-xl border border-pdm-danger-border bg-pdm-danger-tint p-4 text-sm font-medium text-pdm-danger-text">
            Couldn&apos;t load sent answers. Try again.
          </p>
        ) : questions.length === 0 ? (
          <Placeholder>Answers you send appear here.</Placeholder>
        ) : (
          <ul className="space-y-3">
            {questions.map((question) => (
              <SentCard key={question.id} question={question} />
            ))}
          </ul>
        )}
      </PageSection>
    </Page>
  );
}
