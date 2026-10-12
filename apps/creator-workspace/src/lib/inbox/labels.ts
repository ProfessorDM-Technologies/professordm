import {
  INBOUND_MESSAGE_STATUS,
  MESSAGE_CATEGORIES,
  type InboundMessageStatus,
  type MessageCategory,
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
