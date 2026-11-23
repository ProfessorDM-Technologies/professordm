import type { Metadata } from "next";
import { EmptyState } from "@/components/empty-state";
import { PageHeader, PageSection } from "@/components/page-section";

export const metadata: Metadata = {
  title: "Inbox",
};

export default function InboxPage() {
  return (
    <div className="space-y-8">
      <PageHeader title="Inbox" description="Answers to questions you asked in the app." />

      <PageSection id="answers" title="Your questions">
        <EmptyState icon="question" title="Your questions and answers will appear here." />
      </PageSection>
    </div>
  );
}
