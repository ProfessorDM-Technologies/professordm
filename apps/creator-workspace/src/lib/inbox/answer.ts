// Pure: the send gate for answering a question (docs/plans/creator-inbox-spec.md section 7).
// Part B enforces the same rules on the server. No Supabase access here so it can be unit tested.
import { MAX_REPLY_BYTES, MAX_REPLY_LENGTH } from "@/lib/inbox/reply";

export const MAX_TAGS = 5;
export const MAX_TAG_LENGTH = 40;

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Collapse every run of whitespace (spaces, tabs, line breaks) to one space and trim. Same as Part B. */
export function normalizeAnswer(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

export function answerBytes(text: string): number {
  return new TextEncoder().encode(text).length;
}

function words(text: string): string[] {
  const normalized = normalizeAnswer(text);
  return normalized ? normalized.split(" ") : [];
}

/**
 * Share of words that differ between the AI draft and the answer, from 0 (same words) to 1 (all new).
 * Word-level diff: 1 - longest common subsequence / the longer text's word count.
 * Drives the "Your voice" meter only. It is not a gate threshold.
 */
export function changeRatio(aiText: string, text: string): number {
  const a = words(aiText);
  const b = words(text);
  const longest = Math.max(a.length, b.length);
  if (longest === 0) return 0;

  let previous = new Array<number>(b.length + 1).fill(0);
  for (const word of a) {
    const current = new Array<number>(b.length + 1).fill(0);
    for (let j = 1; j <= b.length; j++) {
      current[j] = word === b[j - 1] ? previous[j - 1] + 1 : Math.max(previous[j], current[j - 1]);
    }
    previous = current;
  }
  return 1 - previous[b.length] / longest;
}

export type ParsedTags = { ok: true; tags: string[] } | { ok: false; error: string };

/**
 * Tags from chip input or a comma-separated string: trimmed, lower-cased, empty entries dropped, duplicates removed.
 * More than 5 tags or a tag over 40 characters is an error. An empty list is fine here; the gate asks for one.
 */
export function parseTags(input: string | readonly unknown[]): ParsedTags {
  const raw = typeof input === "string" ? input.split(",") : input;
  const tags = [
    ...new Set(
      raw.flatMap((value) => (typeof value === "string" ? value.split(",") : [])).map((tag) => tag.trim().toLowerCase()),
    ),
  ].filter(Boolean);

  if (tags.some((tag) => tag.length > MAX_TAG_LENGTH)) {
    return { ok: false, error: `Keep each tag to ${MAX_TAG_LENGTH} characters or fewer.` };
  }
  if (tags.length > MAX_TAGS) {
    return { ok: false, error: `Use at most ${MAX_TAGS} tags.` };
  }
  return { ok: true, tags };
}

export type GateIssue =
  | { code: "text_required"; message: string }
  | { code: "text_too_long"; message: string }
  | { code: "edit_required"; message: string }
  | { code: "tags_required"; message: string }
  | { code: "tags_invalid"; message: string }
  | { code: "flags_unreviewed"; message: string };

export type GateInput = {
  text: string;
  /** The AI draft, or null when there was none. Without one the edit rule does not apply. */
  aiText: string | null;
  tags: readonly string[];
  openFlagIds: readonly string[];
  acknowledgedFlagIds: readonly string[];
};

export type GateResult = { ok: boolean; missing: GateIssue[] };

/** Lists only what is still missing, in the order the composer shows it. Send is allowed when the list is empty. */
export function checkSendGate({ text, aiText, tags, openFlagIds, acknowledgedFlagIds }: GateInput): GateResult {
  const missing: GateIssue[] = [];
  const trimmed = text.trim();

  if (!trimmed) {
    missing.push({ code: "text_required", message: "Write your answer" });
  } else if (trimmed.length > MAX_REPLY_LENGTH || answerBytes(trimmed) > MAX_REPLY_BYTES) {
    missing.push({ code: "text_too_long", message: "Shorten your answer to fit Instagram's limit" });
  }
  if (aiText !== null && normalizeAnswer(aiText) !== "" && normalizeAnswer(text) === normalizeAnswer(aiText)) {
    missing.push({ code: "edit_required", message: "Edit the draft so it's in your words" });
  }

  const parsedTags = parseTags(tags);
  if (!parsedTags.ok) {
    missing.push({ code: "tags_invalid", message: parsedTags.error.replace(/\.$/, "") });
  } else if (parsedTags.tags.length === 0) {
    missing.push({ code: "tags_required", message: "Add at least one tag" });
  }

  const acknowledged = new Set(acknowledgedFlagIds);
  if (openFlagIds.some((id) => !acknowledged.has(id))) {
    missing.push({ code: "flags_unreviewed", message: "Review the safety flags" });
  }

  return { ok: missing.length === 0, missing };
}

export type AnswerInput = {
  text: string;
  questionId: string;
  inboundMessageId: string;
  clientRequestId: string;
  tags: string[];
  reviewedFlagIds: string[];
};

export type AnswerErrorCode = "text_required" | "text_too_long" | "tags_required" | "tags_invalid" | "invalid_request";

export type ParsedAnswer =
  | { ok: true; answer: AnswerInput }
  | { ok: false; error: { code: AnswerErrorCode; message: string } };

function isUuid(value: unknown): value is string {
  return typeof value === "string" && UUID_PATTERN.test(value);
}

/** Validates the answer form like parseReply does. The edit rule needs the AI draft, so Part B checks that one. */
export function parseAnswer(fields: {
  text: unknown;
  questionId: unknown;
  inboundMessageId: unknown;
  clientRequestId: unknown;
  tags: readonly unknown[];
  reviewedFlagIds: readonly unknown[];
}): ParsedAnswer {
  const text = typeof fields.text === "string" ? fields.text.replace(/\r\n?/g, "\n").trim() : "";
  if (!text) {
    return { ok: false, error: { code: "text_required", message: "Write your answer before sending." } };
  }
  if (text.length > MAX_REPLY_LENGTH || answerBytes(text) > MAX_REPLY_BYTES) {
    return { ok: false, error: { code: "text_too_long", message: "Your answer is too long. Shorten it before sending." } };
  }

  const tags = parseTags(fields.tags);
  if (!tags.ok) {
    return { ok: false, error: { code: "tags_invalid", message: tags.error } };
  }
  if (tags.tags.length === 0) {
    return { ok: false, error: { code: "tags_required", message: "Add at least one tag." } };
  }

  const { questionId, inboundMessageId, clientRequestId } = fields;
  if (
    !isUuid(questionId) ||
    !isUuid(inboundMessageId) ||
    !isUuid(clientRequestId) ||
    !fields.reviewedFlagIds.every(isUuid)
  ) {
    return {
      ok: false,
      error: { code: "invalid_request", message: "This answer couldn't be sent. Refresh the page and try again." },
    };
  }

  return {
    ok: true,
    answer: {
      text,
      questionId,
      inboundMessageId,
      clientRequestId,
      tags: tags.tags,
      reviewedFlagIds: [...new Set(fields.reviewedFlagIds as string[])],
    },
  };
}

/** What happened to one send press. `error` is the send API's error code, when it sent one. */
export type SendOutcome =
  | { kind: "response"; httpStatus: number; deliveryStatus?: string | null; error?: string | null }
  | { kind: "network_error" }
  | { kind: "timeout" };

/**
 * Whether the next send press may reuse the client_request_id (spec section 8.3).
 * New id when the response proves nothing is in flight: success, any 4xx, and 502 delivery_failed. The API returns
 * the existing row for an id it has seen, so retrying with the old id would never reach Instagram.
 * Same id when we don't know: network error, timeout, other 5xx, or a 200 still pending. The first attempt may
 * have reached Instagram, and the same id makes the retry return that row instead of sending a second DM.
 */
export function nextRequestId(currentId: string, outcome: SendOutcome, newId: () => string = () => crypto.randomUUID()): string {
  if (outcome.kind !== "response") return currentId;
  const { httpStatus } = outcome;
  if (httpStatus >= 200 && httpStatus < 300) {
    return outcome.deliveryStatus === "pending" ? currentId : newId();
  }
  if (httpStatus >= 400 && httpStatus < 500) return newId();
  if (httpStatus === 502 && outcome.error === "delivery_failed") return newId();
  return currentId;
}
