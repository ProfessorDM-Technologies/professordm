import type { Metadata } from "next";
import Link from "next/link";
import { QuestionCard } from "@/components/inbox/question-card";
import { RealtimeRefresh } from "@/components/inbox/realtime-refresh";
import { EmptyState } from "@/components/empty-state";
import { PageHeader, PageSection } from "@/components/page-section";
import { QueueTabs } from "@/components/queue-tabs";
import { RefreshButton } from "@/components/refresh-button";
import { listQuestions } from "@/lib/inbox/questions";

export const metadata: Metadata = {
  title: "Inbox",
};

export default async function InboxPage() {
  const { questions, error, flagsError, loadedAt } = await listQuestions("inbox");

  return (
    <div className="space-y-6">
      <RealtimeRefresh />
      <div className="flex flex-wrap items-end justify-between gap-4">
        <PageHeader title="Inbox" description="Questions waiting for your answer, oldest first." />
        <div className="flex items-center gap-4">
          <Link href="/incoming" className="text-sm font-medium text-pdm-accent-strong underline underline-offset-4">
            All messages →
          </Link>
          <RefreshButton />
        </div>
      </div>
      <QueueTabs current="/inbox" />

      <PageSection id="questions" title="Questions">
        {error ? (
          <p role="alert" className="rounded-2xl border border-pdm-danger-line bg-pdm-danger-bg p-4 text-sm font-medium text-pdm-danger-ink">
            Couldn&apos;t load questions. Try again.
          </p>
        ) : questions.length === 0 ? (
          <EmptyState icon="question" title="You&apos;re all caught up" action={{ href: "/incoming", label: "See all messages" }}>
            New paid questions land here as soon as the AI has drafted an answer for you to review.
          </EmptyState>
        ) : (
          <>
            {flagsError ? (
              <p role="alert" className="rounded-2xl border border-pdm-danger-line bg-pdm-danger-bg p-4 text-sm font-medium text-pdm-danger-ink">
                Safety flags couldn&apos;t be loaded. Open a question to check its flags before answering.
              </p>
            ) : null}
            <ul className="space-y-3">
              {questions.map((question) => (
                <QuestionCard key={question.id} question={question} now={loadedAt} />
              ))}
            </ul>
          </>
        )}
      </PageSection>
    </div>
  );
}
