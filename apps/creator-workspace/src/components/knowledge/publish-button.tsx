"use client";

import { useActionState } from "react";
import { setEntryPublished, type PublishState } from "@/lib/knowledge/actions";

const INITIAL_STATE: PublishState = { status: "idle" };

// Publish / Make private for one answer entry (SCRUM-143). After saving, the page refreshes with the new state.
export function PublishButton({ entryId, published }: { entryId: string; published: boolean }) {
  const [state, formAction, pending] = useActionState(setEntryPublished, INITIAL_STATE);

  return (
    <form action={formAction} className="flex flex-wrap items-center justify-end gap-3">
      <input type="hidden" name="entry_id" value={entryId} />
      <input type="hidden" name="published" value={published ? "false" : "true"} />
      <div aria-live="polite" className="text-sm">
        {state.status === "error" && !pending ? (
          <p role="alert" className="font-medium text-pdm-danger-ink">
            {state.message}
          </p>
        ) : null}
      </div>
      <button
        type="submit"
        disabled={pending}
        className={
          published
            ? "pdm-press min-h-11 rounded-full border border-pdm-border bg-pdm-panel px-4 text-sm font-semibold hover:border-pdm-accent hover:bg-pdm-subtle disabled:opacity-60"
            : "pdm-press min-h-11 rounded-full bg-pdm-accent px-4 text-sm font-semibold text-pdm-on-accent hover:bg-pdm-accent-strong disabled:opacity-60"
        }
      >
        {pending ? "Saving…" : published ? "Make private" : "Publish"}
      </button>
    </form>
  );
}
