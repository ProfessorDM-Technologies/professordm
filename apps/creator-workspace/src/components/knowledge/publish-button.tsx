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
          <p role="alert" className="font-medium text-red-700">
            {state.message}
          </p>
        ) : null}
      </div>
      <button
        type="submit"
        disabled={pending}
        className={
          published
            ? "min-h-11 rounded-lg border border-pdm-border bg-white px-4 text-sm font-medium hover:bg-pdm-surface disabled:opacity-60"
            : "min-h-11 rounded-lg bg-pdm-accent px-4 text-sm font-semibold text-white hover:bg-pdm-accent-strong disabled:opacity-60"
        }
      >
        {pending ? "Saving…" : published ? "Make private" : "Publish"}
      </button>
    </form>
  );
}
