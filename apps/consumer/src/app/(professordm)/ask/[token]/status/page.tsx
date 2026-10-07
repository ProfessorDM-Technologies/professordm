import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Question Status",
};

export default function AskStatusPage() {
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Question status</h1>

      <section aria-labelledby="status-heading" className="space-y-2 rounded-lg border border-pdm-border bg-white p-4">
        <h2 id="status-heading" className="font-medium">
          Current status
        </h2>
        <p className="text-pdm-muted">Your question&apos;s status will appear here.</p>
      </section>

      <p className="text-pdm-muted">Your answer will arrive in your Instagram DMs.</p>
    </div>
  );
}
