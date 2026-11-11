import type { Metadata } from "next";
import { LiveList } from "@/components/ui/live-list";
import { Page } from "@/components/page";
import Link from "next/link";
import { QuestionCard } from "@/components/inbox/question-card";
import { RealtimeRefresh } from "@/components/inbox/realtime-refresh";
import { PageHeader, PageSection } from "@/components/page-section";
import { Placeholder } from "@/components/placeholder";
import { QueueTabs } from "@/components/queue-tabs";
import { RefreshButton } from "@/components/refresh-button";
import { listQuestions } from "@/lib/inbox/questions";

export const metadata: Metadata = {
  title: "Inbox",
};

export default async function InboxPage() {
  const { questions, error, flagsError, loadedAt } = await listQuestions("inbox");

  return (
    <Page className="space-y-6">
      <RealtimeRefresh />
      <div className="flex flex-wrap items-end justify-between gap-4">
        <PageHeader title="Inbox" description="Questions waiting for your answer, oldest first." />
        <div className="flex items-center gap-4">
          <Link href="/incoming" className="text-sm font-medium text-pdm-primary underline underline-offset-4">
            All messages →
          </Link>
          <RefreshButton />
        </div>
      </div>
      <QueueTabs current="/inbox" />

      <PageSection id="questions" title="Questions">
        {error ? (
          <p role="alert" className="rounded-xl border border-pdm-danger-border bg-pdm-danger-tint p-4 text-sm font-medium text-pdm-danger-text">
            Couldn&apos;t load questions. Try again.
          </p>
        ) : questions.length === 0 ? (
          <Placeholder>
            You&apos;re all caught up. New questions appear here as soon as the AI has drafted them.{" "}
            <Link href="/incoming" className="font-medium text-pdm-primary underline underline-offset-4">
              See all messages
            </Link>
          </Placeholder>
        ) : (
          <>
            {flagsError ? (
              <p role="alert" className="rounded-xl border border-pdm-danger-border bg-pdm-danger-tint p-4 text-sm font-medium text-pdm-danger-text">
                Safety flags couldn&apos;t be loaded. Open a question to check its flags before answering.
              </p>
            ) : null}
            <LiveList className="space-y-3">
              {questions.map((question) => (
                <QuestionCard key={question.id} question={question} now={loadedAt} />
              ))}
            </LiveList>
          </>
        )}
      </PageSection>
    </Page>
  );
}
