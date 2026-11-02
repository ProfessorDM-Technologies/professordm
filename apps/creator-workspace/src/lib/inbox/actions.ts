"use server";

import { refresh } from "next/cache";
import { nextRequestId, parseAnswer, type SendOutcome } from "@/lib/inbox/answer";
import { parseReply } from "@/lib/inbox/reply";
import { SESSION_EXPIRED, postToSendApi, type SendApiResult } from "@/lib/inbox/send-api";

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

export type ApproveAnswerState =
  | { status: "idle" }
  | { status: "sent" | "pending"; nextClientRequestId: string }
  | { status: "error"; message: string; nextClientRequestId: string };

// Part B error codes and statuses as plain sentences (spec section 8.3). Nothing she typed is cleared on error.
const ANSWER_MESSAGES = {
  edit_required: "Edit the draft so it's in your words before sending.",
  tags_required: "Add at least one tag.",
  flags_unreviewed: "Review the safety flags first.",
  not_awaiting_answer: "This question was already answered. Refresh to see it.",
  delivery_failed: "Instagram didn't accept the message. Your answer is saved. Try again in a minute.",
  unavailable: "This question is unavailable for your account. Refresh the page.",
  invalid: "This answer couldn't be sent. Refresh the page and try again.",
  unknown: "We couldn't confirm your answer was sent. Wait a moment, then try again. It won't be sent twice.",
} as const;

function answerErrorMessage(result: Extract<SendApiResult, { kind: "response" }>): string {
  const { httpStatus, error } = result;
  if (httpStatus === 401) return SESSION_EXPIRED;
  if (httpStatus === 403 || httpStatus === 404) return ANSWER_MESSAGES.unavailable;
  if (httpStatus === 409) return ANSWER_MESSAGES.not_awaiting_answer;
  if (httpStatus === 422 && (error === "edit_required" || error === "tags_required" || error === "flags_unreviewed")) {
    return ANSWER_MESSAGES[error];
  }
  if (httpStatus === 502 && error === "delivery_failed") return ANSWER_MESSAGES.delivery_failed;
  if (httpStatus >= 400 && httpStatus < 500) return ANSWER_MESSAGES.invalid;
  return ANSWER_MESSAGES.unknown;
}

function toOutcome(result: Exclude<SendApiResult, { kind: "not_sent" }>): SendOutcome {
  return result.kind === "response"
    ? { kind: "response", httpStatus: result.httpStatus, deliveryStatus: result.deliveryStatus, error: result.error }
    : result;
}

// Approves and sends the creator's answer to a question. Part B checks the same gate again on the server,
// claims the question, saves the answer and tags, marks the reviewed flags and delivers the DM.
export async function approveAnswer(_prev: ApproveAnswerState, formData: FormData): Promise<ApproveAnswerState> {
  const fields = {
    text: formData.get("text"),
    questionId: formData.get("question_id"),
    inboundMessageId: formData.get("inbound_message_id"),
    clientRequestId: formData.get("client_request_id"),
    tags: formData.getAll("tags"),
    reviewedFlagIds: formData.getAll("reviewed_flag_ids"),
  };
  const currentId = typeof fields.clientRequestId === "string" ? fields.clientRequestId : crypto.randomUUID();

  const parsed = parseAnswer(fields);
  if (!parsed.ok) {
    return { status: "error", message: parsed.error.message, nextClientRequestId: currentId };
  }
  const { text, questionId, inboundMessageId, clientRequestId, tags, reviewedFlagIds } = parsed.answer;

  const result = await postToSendApi({
    inbound_message_id: inboundMessageId,
    text,
    client_request_id: clientRequestId,
    question_id: questionId,
    tags,
    reviewed_flag_ids: reviewedFlagIds,
  });
  if (result.kind === "not_sent") {
    return { status: "error", message: ANSWER_MESSAGES.invalid, nextClientRequestId: clientRequestId };
  }
  refresh();

  const nextClientRequestId = nextRequestId(clientRequestId, toOutcome(result));
  if (result.kind !== "response") {
    return { status: "error", message: ANSWER_MESSAGES.unknown, nextClientRequestId };
  }
  if (!result.ok) {
    return { status: "error", message: answerErrorMessage(result), nextClientRequestId };
  }
  if (result.deliveryStatus === "sent" || result.deliveryStatus === "pending") {
    return { status: result.deliveryStatus, nextClientRequestId };
  }
  // A repeated request for a send that already failed.
  if (result.deliveryStatus === "failed") {
    return { status: "error", message: ANSWER_MESSAGES.delivery_failed, nextClientRequestId };
  }
  return { status: "error", message: ANSWER_MESSAGES.unknown, nextClientRequestId };
}
