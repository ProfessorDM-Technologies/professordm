import type { Metadata } from "next";
import { MessageRow } from "@/components/inbox/message-row";
import { RealtimeRefresh } from "@/components/inbox/realtime-refresh";
import { EmptyState } from "@/components/empty-state";
import { PageHeader, PageSection } from "@/components/page-section";
import { listInboundThreads } from "@/lib/inbox/queries";

export const metadata: Metadata = {
  title: "Incoming Messages",
};

export default async function IncomingPage() {
  const { threads, error } = await listInboundThreads();
  return (
    <div className="space-y-8">
      <RealtimeRefresh />
      <PageHeader title="Incoming Messages" description="Instagram DMs grouped by question, latest activity first." />

      <PageSection id="messages" title="Messages">
        {error ? (
          <p role="alert">Couldn&apos;t load messages. Try again.</p>
        ) : threads.length === 0 ? (
          <EmptyState icon="inbox" title="No messages yet">
            Instagram DMs to your account land here, grouped by question.
          </EmptyState>
        ) : (
          <ul className="space-y-3">
            {threads.map((thread) => <MessageRow key={thread.head.id} thread={thread} />)}
          </ul>
        )}
      </PageSection>
    </div>
  );
}
