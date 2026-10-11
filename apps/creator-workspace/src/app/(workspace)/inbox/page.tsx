import type { Metadata } from "next";
import { PageHeader, PageSection } from "@/components/page-section";
import { Placeholder } from "@/components/placeholder";
import { QueueTabs } from "@/components/queue-tabs";

export const metadata: Metadata = {
  title: "Inbox",
};

export default function InboxPage() {
  return (
    <div className="space-y-6">
      <PageHeader title="Inbox" description="Paid questions from Instagram and Ask Sweetlife Flora, in one queue." />
      <QueueTabs current="/inbox" />

      <PageSection id="refunds" title="Refund requests">
        <Placeholder>Refund requests will be pinned here.</Placeholder>
      </PageSection>

      <PageSection id="questions" title="Questions">
        <Placeholder>
          Question cards will appear here with source, earnings, draft status, follow-ups left, reply-by time and
          safety flags.
        </Placeholder>
      </PageSection>
    </div>
  );
}
