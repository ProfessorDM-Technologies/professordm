import { describe, expect, it } from "vitest";
import { DECISION_MESSAGES, decisionErrorMessage, parseDecision } from "./decision";

const messageId = "11111111-1111-4111-8111-111111111111";

describe("parseDecision", () => {
  it("accepts both decisions with a message id", () => {
    for (const decision of ["replied", "no_reply_needed"] as const) {
      expect(parseDecision({ messageId, decision })).toEqual({ ok: true, input: { messageId, decision } });
    }
  });

  it("lowercases the message id", () => {
    expect(parseDecision({ messageId: messageId.toUpperCase(), decision: "replied" })).toEqual({
      ok: true,
      input: { messageId, decision: "replied" },
    });
  });

  it("rejects an unknown decision", () => {
    expect(parseDecision({ messageId, decision: "escalate" })).toEqual({ ok: false });
    expect(parseDecision({ messageId, decision: null })).toEqual({ ok: false });
  });

  it("rejects a missing or malformed message id", () => {
    expect(parseDecision({ messageId: null, decision: "replied" })).toEqual({ ok: false });
    expect(parseDecision({ messageId: "not-a-uuid", decision: "replied" })).toEqual({ ok: false });
  });
});

describe("decisionErrorMessage", () => {
  it("maps the database errors to plain sentences", () => {
    expect(decisionErrorMessage({ code: "28000", message: "not_authenticated" })).toBe(DECISION_MESSAGES.session);
    expect(decisionErrorMessage({ code: "P0002", message: "not_found" })).toBe(DECISION_MESSAGES.unavailable);
    expect(decisionErrorMessage({ code: "22023", message: "invalid_decision" })).toBe(DECISION_MESSAGES.invalid);
  });

  it("falls back to a retry message for anything else", () => {
    expect(decisionErrorMessage({ code: "PGRST202", message: "function not found" })).toBe(DECISION_MESSAGES.unknown);
    expect(decisionErrorMessage({})).toBe(DECISION_MESSAGES.unknown);
  });
});
