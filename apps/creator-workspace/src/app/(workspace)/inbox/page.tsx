import type { Metadata } from "next";
import { MessageRow } from "@/components/inbox/message-row";
import { RealtimeRefresh } from "@/components/inbox/realtime-refresh";
import { PageHeader, PageSection } from "@/components/page-section";
import { Placeholder } from "@/components/placeholder";
import { QueueTabs } from "@/components/queue-tabs";
import { RefreshButton } from "@/components/refresh-button";
import { listInboundMessages } from "@/lib/inbox/queries";

export const metadata: Metadata = {
  title: "Inbox",
};

export default async function InboxPage() {
  const { messages, error } = await listInboundMessages();

  return (
    <div className="space-y-6">
      <RealtimeRefresh />
      <div className="flex flex-wrap items-end justify-between gap-4">
        <PageHeader title="Inbox" description="Instagram messages people have sent you, newest first." />
        <RefreshButton />
      </div>
      <QueueTabs current="/inbox" />

      <PageSection id="messages" title="Incoming messages">
        {error ? (
          <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm font-medium text-red-800">
            Couldn&apos;t load messages. Try again.
          </p>
        ) : messages.length === 0 ? (
          <Placeholder>No messages yet. New Instagram DMs will show up here.</Placeholder>
        ) : (
          <ul className="space-y-3">
            {messages.map((message) => (
              <MessageRow key={message.id} message={message} />
            ))}
          </ul>
        )}
      </PageSection>
    </div>
  );
}
