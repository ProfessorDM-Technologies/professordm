import type { Metadata } from "next";
import { PageHeader, PageSection } from "@/components/page-section";
import { Placeholder } from "@/components/placeholder";
import { QueueTabs } from "@/components/queue-tabs";
import { getSessionUser } from "@/lib/auth/session";

export const metadata: Metadata = {
  title: "Moderation",
};

export default async function ModerationPage() {
  const session = await getSessionUser();
  const isAdmin = session?.role === "admin";

  return (
    <div className="space-y-6">
      <PageHeader title="Moderation" description="Flagged questions and answers that need a review." />
      <QueueTabs current="/moderation" />

      <PageSection id="flagged-questions" title="Flagged questions">
        <Placeholder>Questions flagged by safety checks. Review them before you can answer.</Placeholder>
      </PageSection>

      <PageSection id="flagged-answers" title="Answers with the ProfessorDM team">
        <Placeholder>Your answers held for ProfessorDM review, with any feedback.</Placeholder>
      </PageSection>

      <PageSection id="flagged-knowledge" title="Flagged knowledge entries">
        <Placeholder>Knowledge entries flagged by the weekly safety review.</Placeholder>
      </PageSection>

      {isAdmin ? (
        <PageSection id="admin-review" title="ProfessorDM team review">
          <Placeholder>Admin only: approve flagged answers or send them back with feedback.</Placeholder>
        </PageSection>
      ) : null}
    </div>
  );
}
