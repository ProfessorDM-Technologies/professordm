import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Question Status",
};

export default function AskStatusPage() {
  return (
    <div className="space-y-8">
      <h1 className="text-3xl leading-tight font-extrabold sm:text-4xl">Question status</h1>

      <section aria-labelledby="status-heading" className="space-y-2 rounded-2xl border border-pdm-border bg-pdm-panel p-4">
        <h2 id="status-heading" className="font-semibold">
          Current status
        </h2>
        <p className="text-pdm-muted">Your question&apos;s status will appear here.</p>
      </section>

      <p className="text-pdm-muted">Your answer will arrive in your Instagram DMs.</p>
    </div>
  );
}
