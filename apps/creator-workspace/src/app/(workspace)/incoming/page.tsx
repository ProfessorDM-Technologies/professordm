import type { Metadata } from "next";
import { MessageRow } from "@/components/inbox/message-row";
import { RealtimeRefresh } from "@/components/inbox/realtime-refresh";
import { PageHeader, PageSection } from "@/components/page-section";
import { Placeholder } from "@/components/placeholder";
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
          <Placeholder>No messages yet. New Instagram DMs will show up here.</Placeholder>
        ) : (
          <ul className="space-y-3">
            {threads.map((thread) => <MessageRow key={thread.head.id} thread={thread} />)}
          </ul>
        )}
      </PageSection>
    </div>
  );
}
