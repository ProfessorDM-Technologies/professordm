import type { Metadata } from "next";
import { PageHeader, PageSection } from "@/components/page-section";
import { Placeholder } from "@/components/placeholder";

export const metadata: Metadata = {
  title: "Incoming Messages",
};

const CATEGORIES = [
  "Expert Question",
  "Needs Clarification",
  "Social",
  "Spam",
  "Safety Concern",
  "Service Request",
] as const;

export default function IncomingPage() {
  return (
    <div className="space-y-8">
      <PageHeader
        title="Incoming Messages"
        description="Instagram DMs sorted by AI. Fix any label the AI got wrong."
      />

      <PageSection id="categories" title="Categories">
        <ul className="flex flex-wrap gap-2">
          {CATEGORIES.map((category) => (
            <li key={category} className="rounded-full border border-pdm-border bg-white px-3 py-1 text-sm text-pdm-muted">
              {category}
            </li>
          ))}
        </ul>
      </PageSection>

      <PageSection id="messages" title="Messages">
        <Placeholder>Messages will appear here with their AI label, confidence and an override control.</Placeholder>
      </PageSection>
    </div>
  );
}
