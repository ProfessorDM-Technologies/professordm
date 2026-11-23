import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Ask a Question",
};

export default function AskPage() {
  return (
    <div className="space-y-8">
      <div className="space-y-2">
        <h1 className="text-3xl leading-tight font-extrabold sm:text-4xl">Ask a Question</h1>
        <p className="max-w-prose text-pdm-muted">Get a personal answer from me. I&apos;ll review your question and respond directly.</p>
      </div>

      <form className="space-y-6" aria-describedby="ask-form-note">
        <div className="space-y-2">
          <label htmlFor="question" className="block font-semibold">
            Your question
          </label>
          <textarea
            id="question"
            rows={5}
            disabled
            placeholder="Your question from Instagram will appear here."
            className="block w-full rounded-xl border border-pdm-border bg-pdm-panel p-3 text-base transition-colors placeholder:text-pdm-muted focus:border-pdm-accent disabled:cursor-not-allowed disabled:opacity-70"
          />
        </div>

        <fieldset className="space-y-2">
          <legend className="font-semibold">Photos (optional, up to 3)</legend>
          <div className="rounded-2xl border border-dashed border-pdm-border bg-pdm-panel p-4 text-sm text-pdm-muted">
            Photo upload will appear here.
          </div>
        </fieldset>

        <div className="flex items-baseline justify-between gap-3 rounded-2xl border border-pdm-border bg-pdm-panel p-4">
          <span className="font-semibold">Price</span>
          <span className="text-pdm-muted">Shown before you pay</span>
        </div>

        <div className="flex items-start gap-3">
          <input id="acknowledge" type="checkbox" disabled className="mt-0.5 size-5 shrink-0 accent-pdm-accent" />
          <label htmlFor="acknowledge" className="text-sm">
            I understand this is a paid question and my answer will arrive in my Instagram DMs.
          </label>
        </div>

        <button
          type="submit"
          disabled
          className="pdm-press w-full rounded-full bg-pdm-accent px-4 py-3 font-semibold text-pdm-on-accent hover:bg-pdm-accent-strong disabled:cursor-not-allowed disabled:opacity-60"
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
