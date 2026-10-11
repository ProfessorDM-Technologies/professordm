import type { Metadata } from "next";
import { Placeholder } from "@/components/placeholder";

export const metadata: Metadata = {
  title: "Ask the Expert",
};

export default function AskExpertPage() {
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">Ask the Expert</h1>
        <p className="text-flora-muted">Get a personal answer from Sweetlife Flora.</p>
      </div>

      <section aria-labelledby="creator-heading" className="space-y-2">
        <h2 id="creator-heading" className="text-lg font-semibold">
          About the expert
        </h2>
        <Placeholder>Expert details and pricing will appear here.</Placeholder>
      </section>

      <form className="space-y-6" aria-describedby="ask-expert-note">
        <div className="space-y-2">
          <label htmlFor="expert-question" className="block font-medium">
            Your question
          </label>
          <textarea
            id="expert-question"
            rows={5}
            disabled
            className="block w-full rounded-lg border border-flora-border bg-white p-3 text-base disabled:cursor-not-allowed disabled:opacity-70"
          />
        </div>

        <fieldset className="space-y-2">
          <legend className="font-medium">Photos (optional)</legend>
          <Placeholder>Photo upload will appear here.</Placeholder>
        </fieldset>

        <button
          type="submit"
          disabled
          className="w-full rounded-lg bg-flora-accent px-4 py-3 font-semibold text-white hover:bg-flora-accent-strong disabled:cursor-not-allowed disabled:opacity-60"
        >
          Submit and Pay
        </button>
        <p id="ask-expert-note" className="text-center text-sm text-flora-muted">
          Submitting questions is not available yet.
        </p>
      </form>
    </div>
  );
}
