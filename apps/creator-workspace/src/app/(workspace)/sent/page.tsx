import type { Metadata } from "next";
import { PageHeader, PageSection } from "@/components/page-section";
import { Placeholder } from "@/components/placeholder";
import { QueueTabs } from "@/components/queue-tabs";

export const metadata: Metadata = {
  title: "Sent",
};

export default function SentPage() {
  return (
    <div className="space-y-6">
      <PageHeader title="Sent" description="Answers you've sent, follow-ups and ratings." />
      <QueueTabs current="/sent" />

      <PageSection id="sent" title="Sent answers">
        <Placeholder>
          Sent answers will appear here with follow-ups used, the 3-day hold, acceptance, rating and when funds are
          released.
        </Placeholder>
      </PageSection>
    </div>
  );
}
