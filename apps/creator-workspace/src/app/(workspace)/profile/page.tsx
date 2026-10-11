import type { Metadata } from "next";
import Link from "next/link";
import { PageHeader, PageSection } from "@/components/page-section";
import { Placeholder } from "@/components/placeholder";

export const metadata: Metadata = {
  title: "Profile",
};

const SETTINGS = [
  "Photo and bio",
  "Question price",
  "Follow-ups included",
  "Expected answer time",
  "Payout method and mode",
  "Notification preferences",
  "Knowledge Database on or off",
  "Subscription price and subscriber discount",
] as const;

export default function ProfilePage() {
  return (
    <div className="space-y-8">
      <PageHeader title="Profile" description="Your public profile, pricing and payout settings." />

      <PageSection id="settings" title="Settings">
        <ul className="divide-y divide-pdm-border rounded-lg border border-pdm-border bg-white">
          {SETTINGS.map((setting) => (
            <li key={setting} className="px-4 py-3 text-sm text-pdm-muted">
              {setting}
            </li>
          ))}
        </ul>
        <Placeholder>Editing these settings is not available yet.</Placeholder>
      </PageSection>

      <PageSection id="knowledge" title="Knowledge Database">
        <Link href="/knowledge" className="inline-block font-semibold text-pdm-accent-strong underline underline-offset-4">
          Manage your Knowledge Database
        </Link>
      </PageSection>
    </div>
  );
}
