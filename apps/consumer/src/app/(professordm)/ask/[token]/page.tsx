import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Ask a Question",
};

export default function AskPage() {
  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <h1 className="text-2xl font-semibold tracking-tight">Ask a Question</h1>
        <p className="text-pdm-muted">Get a personal answer from me. I&apos;ll review your question and respond directly.</p>
      </div>

      <form className="space-y-6" aria-describedby="ask-form-note">
        <div className="space-y-2">
          <label htmlFor="question" className="block font-medium">
            Your question
          </label>
          <textarea
            id="question"
            rows={5}
            disabled
            placeholder="Your question from Instagram will appear here."
            className="block w-full rounded-lg border border-pdm-border bg-white p-3 text-base disabled:cursor-not-allowed disabled:opacity-70"
          />
        </div>

        <fieldset className="space-y-2">
          <legend className="font-medium">Photos (optional, up to 3)</legend>
          <div className="rounded-lg border border-dashed border-pdm-border bg-white p-4 text-sm text-pdm-muted">
            Photo upload will appear here.
          </div>
        </fieldset>

        <div className="flex items-baseline justify-between rounded-lg border border-pdm-border bg-white p-4">
          <span className="font-medium">Price</span>
          <span className="text-pdm-muted">Shown before you pay</span>
        </div>

        <div className="flex items-start gap-3">
          <input id="acknowledge" type="checkbox" disabled className="mt-1 size-5 shrink-0" />
          <label htmlFor="acknowledge" className="text-sm">
            I understand this is a paid question and my answer will arrive in my Instagram DMs.
          </label>
        </div>

        <button
          type="submit"
          disabled
          className="w-full rounded-lg bg-pdm-accent px-4 py-3 font-semibold text-white hover:bg-pdm-accent-strong disabled:cursor-not-allowed disabled:opacity-60"
        >
          Submit Question
        </button>
        <p id="ask-form-note" className="text-center text-sm text-pdm-muted">
          Checkout is not available yet.
        </p>
      </form>
    </div>
  );
}
