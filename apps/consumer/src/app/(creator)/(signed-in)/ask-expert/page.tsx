import type { Metadata } from "next";
import { PageHeader } from "@/components/page-section";
import { Placeholder } from "@/components/placeholder";

export const metadata: Metadata = {
  title: "Ask the Expert",
};

export default function AskExpertPage() {
  return (
    <div className="space-y-8">
      <PageHeader title="Ask the Expert" description="Get a personal answer from Sweetlife Flora." />

      <section aria-labelledby="creator-heading" className="space-y-2">
        <h2 id="creator-heading" className="text-lg font-bold">
          About the expert
        </h2>
        <Placeholder>Expert details and pricing will appear here.</Placeholder>
      </section>

      <form className="space-y-6" aria-describedby="ask-expert-note">
        <div className="space-y-2">
          <label htmlFor="expert-question" className="block font-semibold">
            Your question
          </label>
          <textarea
            id="expert-question"
            rows={5}
            disabled
            className="block w-full rounded-xl border border-pdm-border bg-pdm-panel p-3 text-base transition-colors focus:border-pdm-accent disabled:cursor-not-allowed disabled:opacity-70"
          />
        </div>

        <fieldset className="space-y-2">
          <legend className="font-semibold">Photos (optional)</legend>
          <Placeholder>Photo upload will appear here.</Placeholder>
        </fieldset>

        <button
          type="submit"
          disabled
          className="pdm-press w-full rounded-full bg-pdm-accent px-4 py-3 font-semibold text-pdm-on-accent hover:bg-pdm-accent-strong disabled:cursor-not-allowed disabled:opacity-60"
        >
          Submit and Pay
        </button>
        <p id="ask-expert-note" className="text-center text-sm text-pdm-muted">
          Submitting questions is not available yet.
        </p>
      </form>
    </div>
  );
}
