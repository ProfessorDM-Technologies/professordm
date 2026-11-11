import {
  INBOUND_MESSAGE_STATUS,
  MESSAGE_CATEGORIES,
  OUTBOUND_TYPES,
  QUESTION_STATUS,
  type InboundMessageStatus,
  type MessageCategory,
  type OutboundType,
  type QuestionStatus,
} from "@professordm/contracts";

export const CATEGORY_LABELS: Record<MessageCategory, string> = {
  expert_question: "Expert Question",
  needs_clarification: "Needs Clarification",
  social: "Social",
  spam_irrelevant: "Spam",
  safety_concern: "Safety Concern",
  service_request: "Service Request",
};

export const INBOUND_STATUS_LABELS: Record<InboundMessageStatus, string> = {
  received: "Received",
  triaging: "Sorting",
  closed_no_action: "No action needed",
  blocked: "Blocked",
  service_routed: "Sent to service",
  awaiting_clarification: "Waiting for details",
  reassessing: "Re-checking",
  ready_for_question: "Ready for question",
  creator_decision: "Needs your decision",
};

export const OUTBOUND_TYPE_LABELS: Record<OutboundType, string> = {
  ask_link: "Ask link",
  clarification: "Clarification",
  confirmation: "Confirmation",
  answer: "Answer",
  followup: "Follow-up reply",
  rating_prompt: "Rating request",
  survey: "Survey",
  decline: "Decline",
  status: "Status update",
};

export const QUESTION_STATUS_LABELS: Record<QuestionStatus, string> = {
  pending_payment: "Waiting for payment",
  paid: "AI is drafting",
  drafting: "AI is drafting",
  awaiting_creator: "Waiting for your answer",
  approved: "Sending",
  final_screening: "Final safety check",
  professordm_review: "With the ProfessorDM team",
  delivering: "Sending",
  delivered: "Delivered",
  accepted: "Accepted",
  closed: "Closed",
  declined_refunded: "Declined and refunded",
  refund_requested: "Refund requested",
  refunded: "Refunded",
  refund_denied: "Refund denied",
  delivery_failed: "Delivery failed",
};

// drafts.knowledge_coverage and drafts.reason are database checks (migration 009), not contracts enums.
export const KNOWLEDGE_COVERAGE = ["high", "partial", "none"] as const;
export type KnowledgeCoverage = (typeof KNOWLEDGE_COVERAGE)[number];

export const COVERAGE_LABELS: Record<KnowledgeCoverage, string> = {
  high: "Well covered by your guides",
  partial: "Partly covered by your guides",
  none: "Not in your guides",
};

export const NO_DRAFT_REASONS = ["no_coverage", "invalid_output", "safety_blocked", "empty_question"] as const;
export type NoDraftReason = (typeof NO_DRAFT_REASONS)[number];

export const NO_DRAFT_REASON_LABELS: Record<NoDraftReason, string> = {
  no_coverage: "Your guides don't cover this yet",
  invalid_output: "The AI draft didn't pass its quality checks",
  safety_blocked: "The AI held back a draft for safety",
  empty_question: "The question had no text",
};

export const FLAG_LABELS = {
  harassment: "Harassing language",
  safety_concern: "Safety concern",
  risk_topic: "Sensitive topic",
  fallback: "Flagged",
} as const;

export const UNCLASSIFIED_LABEL = "Not classified yet";

export function isMessageCategory(value: unknown): value is MessageCategory {
  return typeof value === "string" && (MESSAGE_CATEGORIES as readonly string[]).includes(value);
}

export function isInboundStatus(value: unknown): value is InboundMessageStatus {
  return typeof value === "string" && (INBOUND_MESSAGE_STATUS as readonly string[]).includes(value);
}

export function categoryLabel(value: string | null): string {
  return isMessageCategory(value) ? CATEGORY_LABELS[value] : UNCLASSIFIED_LABEL;
}

export function inboundStatusLabel(value: string | null): string | null {
  return isInboundStatus(value) ? INBOUND_STATUS_LABELS[value] : null;
}

// Outbound types the creator writes. Everything else (clarifications, declines, ask links, prompts) is automated.
const CREATOR_AUTHORED_TYPES: readonly string[] = ["answer", "followup"];

/** True when an outbound message is the creator's own words, shown on Soft Sage in threads (brand spec section 3.1). */
export function isCreatorAuthored(outboundType: string | null | undefined): boolean {
  return typeof outboundType === "string" && CREATOR_AUTHORED_TYPES.includes(outboundType);
}

export function outboundTypeLabel(value: string): string {
  return (OUTBOUND_TYPES as readonly string[]).includes(value) ? OUTBOUND_TYPE_LABELS[value as OutboundType] : value;
}

// outbound_messages.status is free text in the schema (no enum in contracts yet), so show it readably.
export function outboundStatusLabel(value: string | null | undefined): string | null {
  if (!value) return null;
  const text = value.replaceAll("_", " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function questionStatusLabel(value: string | null | undefined): string | null {
  return typeof value === "string" && (QUESTION_STATUS as readonly string[]).includes(value)
    ? QUESTION_STATUS_LABELS[value as QuestionStatus]
    : null;
}

export function coverageLabel(value: string | null | undefined): string | null {
  return typeof value === "string" && (KNOWLEDGE_COVERAGE as readonly string[]).includes(value)
    ? COVERAGE_LABELS[value as KnowledgeCoverage]
    : null;
}

export function noDraftReasonLabel(value: string | null | undefined): string | null {
  return typeof value === "string" && (NO_DRAFT_REASONS as readonly string[]).includes(value)
    ? NO_DRAFT_REASON_LABELS[value as NoDraftReason]
    : null;
}

// safety_flags.detail is a fixed vocabulary (migration 009), never DM text, so it is safe to show.
export function flagLabel(flag: { layer: string | null; category: string | null; detail: string | null }): string {
  if (flag.layer === "moderation" && flag.category === "harassment") return FLAG_LABELS.harassment;
  if (flag.layer === "policy" && flag.category === "safety_concern") return FLAG_LABELS.safety_concern;
  if (flag.layer === "policy" && flag.category === "risk_topic") {
    return flag.detail ? `${FLAG_LABELS.risk_topic}: ${flag.detail.replaceAll("_", " ")}` : FLAG_LABELS.risk_topic;
  }
  return flag.category ? `${FLAG_LABELS.fallback}: ${flag.category.replaceAll("_", " ")}` : FLAG_LABELS.fallback;
}
