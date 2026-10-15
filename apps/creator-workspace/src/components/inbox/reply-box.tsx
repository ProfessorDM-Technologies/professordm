"use client";

import { useActionState, useState } from "react";
import { sendReply, type SendReplyState } from "@/lib/inbox/actions";
import { MAX_REPLY_LENGTH } from "@/lib/inbox/reply";

const INITIAL_STATE: SendReplyState = { status: "idle" };

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

  return (
    <form action={formAction} className="space-y-3 rounded-lg border border-pdm-border bg-white p-4">
      <input type="hidden" name="inbound_message_id" value={inboundMessageId} />
      <input type="hidden" name="client_request_id" value={requestId} />

      <label htmlFor="reply-text" className="block font-medium">
        Reply to {recipient}
      </label>
      <textarea
        id="reply-text"
        name="text"
        rows={4}
        value={text}
        onChange={(event) => setText(event.target.value)}
        readOnly={pending || state.status === "pending"}
        maxLength={MAX_REPLY_LENGTH}
        aria-invalid={state.status === "error" ? true : undefined}
        aria-describedby="reply-status"
        className="block w-full rounded-lg border border-pdm-border bg-white p-3 text-base"
      />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <div id="reply-status" aria-live="polite" className="text-sm">
          {state.status === "error" ? (
            <p role="alert" className="font-medium text-red-700">
              {state.message}
            </p>
          ) : state.status === "sent" ? (
            <p className="font-medium text-green-800">Reply sent to Instagram.</p>
          ) : state.status === "pending" ? (
            <p>This reply is processing. Check its status before composing another reply.</p>
          ) : null}
        </div>

        <button
          type="submit"
          disabled={pending || empty}
          className="min-h-11 rounded-lg bg-pdm-accent px-5 font-semibold text-white hover:bg-pdm-accent-strong disabled:opacity-60"
        >
          {pending ? "Sending…" : state.status === "pending" ? "Check status" : "Send"}
        </button>
      </div>
    </form>
  );
}
