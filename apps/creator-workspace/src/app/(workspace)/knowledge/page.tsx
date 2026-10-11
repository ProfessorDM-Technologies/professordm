import type { Metadata } from "next";
import { PageHeader, PageSection } from "@/components/page-section";
import { Placeholder } from "@/components/placeholder";

export const metadata: Metadata = {
  title: "Knowledge Database",
};

export default function KnowledgePage() {
  return (
    <div className="space-y-8">
      <PageHeader
        title="Knowledge Database"
        description="Your past answers and facts. The AI searches these first when drafting."
      />

      <PageSection id="entries" title="Entries">
        <Placeholder>Past answers and facts will appear here. Edit, tag or unpublish them.</Placeholder>
      </PageSection>

      <PageSection id="add" title="Add a fact">
        <Placeholder>A form to add a new fact by hand will appear here.</Placeholder>
      </PageSection>
    </div>
  );
}
