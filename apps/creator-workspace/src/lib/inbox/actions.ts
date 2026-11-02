"use server";

import { refresh } from "next/cache";
import { parseReply } from "@/lib/inbox/reply";
import { SESSION_EXPIRED, postToSendApi } from "@/lib/inbox/send-api";

export type SendReplyState =
  | { status: "idle" }
  | { status: "sent"; clientRequestId: string }
  | { status: "pending"; clientRequestId: string }
  | { status: "error"; message: string };

const SEND_FAILED = "Your reply couldn't be delivered. Check the conversation before trying again.";

// The API verifies the user token, reserves the outbound ID, and delivers to Instagram.
export async function sendReply(_prev: SendReplyState, formData: FormData): Promise<SendReplyState> {
  const parsed = parseReply({
    text: formData.get("text"),
    inboundMessageId: formData.get("inbound_message_id"),
    clientRequestId: formData.get("client_request_id"),
  });
  if (!parsed.ok) {
    return { status: "error", message: parsed.error };
  }
  const { text, inboundMessageId, clientRequestId } = parsed.reply;

  const result = await postToSendApi({ inbound_message_id: inboundMessageId, text, client_request_id: clientRequestId });
  if (result.kind === "not_sent") {
    return { status: "error", message: SEND_FAILED };
  }
  refresh();
  if (result.kind !== "response") {
    return { status: "error", message: SEND_FAILED };
  }
  if (!result.ok) {
    if (result.httpStatus === 401) {
      return { status: "error", message: SESSION_EXPIRED };
    }
    if (result.httpStatus === 403 || result.httpStatus === 404) {
      return { status: "error", message: "This conversation is unavailable for your account. Refresh the page." };
    }
    if (result.httpStatus === 409) {
      return { status: "error", message: "This reply couldn't be sent. Check the conversation, then refresh before composing a new reply." };
    }
    return { status: "error", message: SEND_FAILED };
  }
  if (result.deliveryStatus !== "sent" && result.deliveryStatus !== "pending") {
    return { status: "error", message: SEND_FAILED };
  }
  return { status: result.deliveryStatus, clientRequestId };
}
