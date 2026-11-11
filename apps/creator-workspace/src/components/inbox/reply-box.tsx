"use client";

import { useRouter } from "next/navigation";
import { useActionState, useState } from "react";
import { usePendingReply } from "@/components/inbox/message-pane";
import { buttonClass } from "@/components/ui/button-styles";
import { sendReply, type SendReplyState } from "@/lib/inbox/actions";
import { MAX_REPLY_LENGTH } from "@/lib/inbox/reply";

const INITIAL_STATE: SendReplyState = { status: "idle" };

/** Composer docked to the bottom of the conversation pane (UI v2 spec, requirement 4). It never scrolls away. */
export function ReplyBox({ inboundMessageId, recipient }: { inboundMessageId: string; recipient: string }) {
  const [text, setText] = useState("");
  // One id per Send press. A double click submits the same id, so the database keeps only one row.
  const [requestId, setRequestId] = useState(() => crypto.randomUUID());

  const router = useRouter();
  const pendingReply = usePendingReply();

  const [state, formAction, pending] = useActionState(async (prev: SendReplyState, formData: FormData) => {
    // Optimistic bubble in the pane above while the send runs (UI v2 spec, motion b).
    pendingReply?.showPending(String(formData.get("text") ?? "").trim() || null);
    const result = await sendReply(prev, formData);
    if (result.status === "sent") {
      setText("");
      setRequestId(crypto.randomUUID());
      // Refresh inside the action so the optimistic bubble stays until the real message is on screen.
      router.refresh();
    }
    return result;
  }, INITIAL_STATE);

  const empty = text.trim().length === 0;

  return (
    <form action={formAction} className="space-y-2 border-t border-pdm-border bg-pdm-card p-3">
      <input type="hidden" name="inbound_message_id" value={inboundMessageId} />
      <input type="hidden" name="client_request_id" value={requestId} />

      <label htmlFor="reply-text" className="sr-only">
        Reply to {recipient}
      </label>
      <div className="flex items-end gap-2">
        <textarea
          id="reply-text"
          name="text"
          rows={1}
          value={text}
          placeholder={`Reply to ${recipient}`}
          onChange={(event) => setText(event.target.value)}
          readOnly={pending || state.status === "pending"}
          maxLength={MAX_REPLY_LENGTH}
          aria-invalid={state.status === "error" ? true : undefined}
          aria-describedby="reply-status"
          className="block max-h-40 min-h-11 w-full resize-none rounded-xl border border-pdm-border-strong bg-pdm-canvas px-3.5 py-2.5 text-base field-sizing-content placeholder:text-pdm-muted motion-safe:transition-colors focus:bg-pdm-card"
        />
        <button type="submit" disabled={pending || empty} className={buttonClass("primary", "md", "shrink-0 px-5")}>
          {pending ? "Sending…" : state.status === "pending" ? "Check status" : "Send"}
        </button>
      </div>

      <div id="reply-status" aria-live="polite" className="min-h-5 px-1 text-xs">
        {state.status === "error" ? (
          <p role="alert" className="font-medium text-pdm-danger-text">
            {state.message}
          </p>
        ) : state.status === "sent" ? (
          <p className="font-medium text-pdm-success-text">Reply sent to Instagram.</p>
        ) : state.status === "pending" ? (
          <p className="text-pdm-muted">This reply is processing. Check its status before composing another reply.</p>
        ) : null}
      </div>
    </form>
  );
}
