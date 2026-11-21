"use client";

import { useActionState } from "react";
import { decideMessage, type DecideMessageState } from "@/lib/inbox/actions";

const INITIAL_STATE: DecideMessageState = { status: "idle" };

// "I replied" / "No reply needed" on a DM in "Needs your decision" (SCRUM-140). The pressed button's value is
// the decision. Once saved, the page refreshes and the row leaves the list.
export function DecisionButtons({ messageId }: { messageId: string }) {
  const [state, formAction, pending] = useActionState(decideMessage, INITIAL_STATE);
  const locked = pending || state.status === "done";

  return (
    <form action={formAction} className="space-y-2">
      <input type="hidden" name="message_id" value={messageId} />
      <div className="flex flex-wrap gap-3">
        <button
          type="submit"
          name="decision"
          value="replied"
          disabled={locked}
          className="pdm-press min-h-11 rounded-full bg-pdm-accent px-4 text-sm font-semibold text-pdm-on-accent hover:bg-pdm-accent-strong disabled:opacity-60"
        >
          I replied
        </button>
        <button
          type="submit"
          name="decision"
          value="no_reply_needed"
          disabled={locked}
          className="pdm-press min-h-11 rounded-full border border-pdm-border bg-pdm-panel px-4 text-sm font-semibold hover:border-pdm-accent hover:bg-pdm-subtle disabled:opacity-60"
        >
          No reply needed
        </button>
      </div>
      <div aria-live="polite" className="text-sm">
        {pending ? (
          <p className="text-pdm-muted">Saving…</p>
        ) : state.status === "error" ? (
          <p role="alert" className="font-medium text-pdm-danger-ink">
            {state.message}
          </p>
        ) : state.status === "done" ? (
          <p className="font-medium text-pdm-success-ink">Saved.</p>
        ) : null}
      </div>
    </form>
  );
}
