// Deciding on a DM in "Needs your decision" (docs/plans/scrum-140-moderation-decisions-spec.md).
// The database function record_message_decision (migration 012) does the write; this file checks the form
// fields and turns its errors into plain sentences.

export const DECISIONS = ["replied", "no_reply_needed"] as const;
export type Decision = (typeof DECISIONS)[number];

export type DecisionInput = { messageId: string; decision: Decision };

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export const DECISION_MESSAGES = {
  session: "Your session expired. Sign in again.",
  unavailable: "This message is unavailable for your account. Refresh the page.",
  invalid: "This decision couldn't be saved. Refresh the page and try again.",
  unknown: "Couldn't save your decision. Try again.",
} as const;

function isDecision(value: unknown): value is Decision {
  return typeof value === "string" && (DECISIONS as readonly string[]).includes(value);
}

export function parseDecision(fields: {
  messageId: unknown;
  decision: unknown;
}): { ok: true; input: DecisionInput } | { ok: false } {
  const { messageId, decision } = fields;
  if (typeof messageId !== "string" || !UUID_PATTERN.test(messageId) || !isDecision(decision)) {
    return { ok: false };
  }
  return { ok: true, input: { messageId: messageId.toLowerCase(), decision } };
}

// Error codes raised by record_message_decision: 28000 not_authenticated, P0002 not_found, 22023 invalid_decision.
export function decisionErrorMessage(error: { code?: string; message?: string }): string {
  if (error.code === "28000") return DECISION_MESSAGES.session;
  if (error.code === "P0002") return DECISION_MESSAGES.unavailable;
  if (error.code === "22023") return DECISION_MESSAGES.invalid;
  return DECISION_MESSAGES.unknown;
}
