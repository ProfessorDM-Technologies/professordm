// Shared status enums + queue job types. Source of truth: docs/architecture/BASELINE.md section 2.
// Every service imports from here. Change it only through a PR reviewed by Karthik + affected leads.

export const MESSAGE_CATEGORIES = [
  "expert_question",
  "needs_clarification",
  "social",
  "spam_irrelevant",
  "safety_concern",
  "service_request",
] as const;
export type MessageCategory = (typeof MESSAGE_CATEGORIES)[number];

export const INBOUND_MESSAGE_STATUS = [
  "received",
  "triaging",
  "closed_no_action",
  "blocked",
  "service_routed",
  "awaiting_clarification",
  "reassessing",
  "ready_for_question",
  "creator_decision",
] as const;
export type InboundMessageStatus = (typeof INBOUND_MESSAGE_STATUS)[number];

export const QUESTION_STATUS = [
  "pending_payment",
  "paid",
  "drafting",
  "awaiting_creator",
  "approved",
  "final_screening",
  "professordm_review",
  "delivering",
  "delivered",
  "accepted",
  "closed",
  "declined_refunded",
  "refund_requested",
  "refunded",
  "refund_denied",
  "delivery_failed",
] as const;
export type QuestionStatus = (typeof QUESTION_STATUS)[number];

export const QUESTION_SOURCES = ["instagram", "knowledge_app"] as const;
export type QuestionSource = (typeof QUESTION_SOURCES)[number];

export const AI_JOB_TYPES = [
  "triage",
  "reassess",
  "draft",
  "followup",
  "final_screen",
  "embed",
  "ingest",
  "kb_safety_review",
] as const;
export type AiJobType = (typeof AI_JOB_TYPES)[number];

export const OUTBOUND_TYPES = [
  "ask_link",
  "clarification",
  "confirmation",
  "answer",
  "followup",
  "rating_prompt",
  "survey",
  "decline",
  "status",
] as const;
export type OutboundType = (typeof OUTBOUND_TYPES)[number];

export const DELIVERY_MODES = ["standard", "human_agent", "fallback_email"] as const;
export type DeliveryMode = (typeof DELIVERY_MODES)[number];

/** Envelope on every SQS message. Consumers must be idempotent on `id`. */
export interface JobEnvelope<T extends string, P = Record<string, unknown>> {
  v: 1;
  type: T;
  id: string;
  creatorId: string;
  traceId: string;
  createdAt: string; // ISO 8601
  payload: P;
}
