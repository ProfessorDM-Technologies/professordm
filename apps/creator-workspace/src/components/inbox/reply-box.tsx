"use client";

import { useActionState, useState } from "react";
import { sendReply, type SendReplyState } from "@/lib/inbox/actions";
import { MAX_REPLY_LENGTH } from "@/lib/inbox/reply";

const INITIAL_STATE: SendReplyState = { status: "idle" };

// Chat composer pinned to the bottom of the conversation pane (it never scrolls with the messages).
// Enter sends, Shift+Enter adds a line, like Instagram on the web.
export function ReplyBox({ inboundMessageId, recipient }: { inboundMessageId: string; recipient: string }) {
  const [text, setText] = useState("");
  // One id per Send press. A double click submits the same id, so the database keeps only one row.
  const [requestId, setRequestId] = useState(() => crypto.randomUUID());

  const [state, formAction, pending] = useActionState(async (prev: SendReplyState, formData: FormData) => {
    const result = await sendReply(prev, formData);
    if (result.status === "sent") {
      setText("");
      setRequestId(crypto.randomUUID());
    }
    return result;
  }, INITIAL_STATE);

  const empty = text.trim().length === 0;
  const locked = pending || state.status === "pending";

  return (
    <form action={formAction} className="space-y-2 border-t border-pdm-border bg-pdm-panel px-3 py-3 sm:px-4">
      <input type="hidden" name="inbound_message_id" value={inboundMessageId} />
      <input type="hidden" name="client_request_id" value={requestId} />

      <div id="reply-status" aria-live="polite" className="text-sm empty:hidden">
        {state.status === "error" ? (
          <p role="alert" className="font-medium text-pdm-danger-ink">
            {state.message}
          </p>
        ) : state.status === "sent" ? (
          <p className="font-medium text-pdm-success-ink">Reply sent to Instagram.</p>
        ) : state.status === "pending" ? (
          <p>This reply is processing. Check its status before composing another reply.</p>
        ) : null}
      </div>

      <div className="flex items-end gap-2 rounded-3xl border border-pdm-border bg-pdm-surface py-1.5 pr-1.5 pl-4 transition-colors focus-within:border-pdm-accent">
        <label htmlFor="reply-text" className="sr-only">
          Reply to {recipient}
        </label>
        <textarea
          id="reply-text"
          name="text"
          rows={1}
          value={text}
          placeholder={`Message ${recipient}…`}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              if (!empty && !locked) event.currentTarget.form?.requestSubmit();
            }
          }}
          readOnly={locked}
          maxLength={MAX_REPLY_LENGTH}
          aria-invalid={state.status === "error" ? true : undefined}
          aria-describedby="reply-status"
          className="field-sizing-content block max-h-36 min-h-10 flex-1 resize-none bg-transparent py-2 text-base text-pdm-ink outline-none placeholder:text-pdm-muted"
        />
        <button
          type="submit"
          disabled={pending || empty}
          className="pdm-press min-h-10 shrink-0 rounded-full bg-pdm-accent px-5 text-sm font-semibold text-pdm-on-accent hover:bg-pdm-accent-strong disabled:opacity-50"
        >
          {pending ? "Sending…" : state.status === "pending" ? "Check status" : "Send"}
        </button>
      </div>
    </form>
  );
}
