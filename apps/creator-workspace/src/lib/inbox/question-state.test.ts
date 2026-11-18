import { describe, expect, it } from "vitest";
import { cardState, flagHint, waitLabel, type CardDraft } from "./question-state";

const question = (status: string, openFlagIds: string[] = []) => ({ status, openFlagIds });
const ready: CardDraft = { status: "ready", coverage: "partial", reason: null };
const noDraft: CardDraft = { status: "no_draft", coverage: "none", reason: "no_coverage" };

describe("cardState", () => {
  it("shows AI is drafting for paid and drafting, with no action", () => {
    for (const status of ["paid", "drafting"]) {
      expect(cardState(question(status), null, null)).toEqual({
        label: "AI is drafting",
        tone: "progress",
        hint: "Usually ready in under 20 seconds.",
        action: null,
      });
    }
  });

  it("shows Sending for approved and delivering", () => {
    for (const status of ["approved", "delivering"]) {
      expect(cardState(question(status), ready, { status: "pending" })).toEqual({
        label: "Sending",
        tone: "progress",
        hint: "Delivering to Instagram…",
        action: "View",
      });
    }
  });

  it("asks to review a flag first", () => {
    expect(cardState(question("awaiting_creator", ["f1"]), null, null)).toEqual({
      label: "Review flag first",
      tone: "danger",
      hint: "A safety check flagged this. Review it before answering.",
      action: "Review",
    });
  });

  it("names the flag and the next step when the flag details are known", () => {
    const flagged = {
      status: "awaiting_creator",
      openFlagIds: ["f1"],
      openFlags: [{ targetType: "message" as const, layer: "policy", category: "risk_topic", detail: "pet_toxicity" }],
    };
    expect(cardState(flagged, ready, null)).toEqual({
      label: "Review flag first",
      tone: "danger",
      hint: "Sensitive topic: pet toxicity on the message. Tick “I've reviewed this”, then answer.",
      action: "Review",
    });
  });

  it("puts a flag before a ready draft and before a failed send", () => {
    expect(cardState(question("awaiting_creator", ["f1"]), ready, { status: "failed" }).label).toBe("Review flag first");
  });

  it("drafting beats an open flag", () => {
    expect(cardState(question("drafting", ["f1"]), null, null).label).toBe("AI is drafting");
  });

  it("shows Send failed after a failed send", () => {
    expect(cardState(question("awaiting_creator"), ready, { status: "failed" })).toEqual({
      label: "Send failed",
      tone: "danger",
      hint: "Your answer was saved. Open it to try again.",
      action: "Try again",
    });
  });

  it("puts a failed send before a ready draft and before no drafts row", () => {
    expect(cardState(question("awaiting_creator"), ready, { status: "failed" }).label).toBe("Send failed");
    expect(cardState(question("awaiting_creator"), null, { status: "failed" }).label).toBe("Send failed");
  });

  it("shows Draft ready with the coverage line", () => {
    expect(cardState(question("awaiting_creator"), ready, null)).toEqual({
      label: "Draft ready",
      tone: "accent",
      hint: "Partly covered by your guides",
      action: "Review & answer",
    });
    expect(cardState(question("awaiting_creator"), { ...ready, coverage: "high" }, null).hint).toBe(
      "Well covered by your guides",
    );
  });

  it("keeps a ready draft when the last send did not fail", () => {
    expect(cardState(question("awaiting_creator"), ready, { status: "sent" }).label).toBe("Draft ready");
  });

  it("shows Answer by hand with the reason line", () => {
    expect(cardState(question("awaiting_creator"), noDraft, null)).toEqual({
      label: "Answer by hand",
      tone: "neutral",
      hint: "Your guides don't cover this yet",
      action: "Answer",
    });
    expect(cardState(question("awaiting_creator"), { ...noDraft, reason: "safety_blocked" }, null).hint).toBe(
      "The AI held back a draft for safety",
    );
  });

  it("shows AI unavailable when there is no drafts row", () => {
    expect(cardState(question("awaiting_creator"), null, null)).toEqual({
      label: "AI unavailable",
      tone: "neutral",
      hint: "The AI couldn't draft this. Answer it yourself.",
      action: "Answer",
    });
  });

  it("falls back to plain text for missing coverage, missing reason and unexpected draft statuses", () => {
    expect(cardState(question("awaiting_creator"), { ...ready, coverage: null }, null).hint).toBe(
      "Review the AI draft before you send it.",
    );
    expect(cardState(question("awaiting_creator"), { ...noDraft, reason: null }, null).hint).toBe("Not in your guides");
    expect(cardState(question("awaiting_creator"), { status: "approved", coverage: null, reason: null }, null)).toEqual({
      label: "Waiting for your answer",
      tone: "neutral",
      hint: "Open it to write your answer.",
      action: "Answer",
    });
  });
});

describe("waitLabel", () => {
  const now = Date.parse("2026-11-02T12:00:00Z");
  const ago = (ms: number) => new Date(now - ms).toISOString();

  it("uses human units", () => {
    expect(waitLabel(ago(30_000), now)).toBe("just now");
    expect(waitLabel(ago(5 * 60_000), now)).toBe("waiting 5 min");
    expect(waitLabel(ago(2 * 3_600_000 + 10 * 60_000), now)).toBe("waiting 2 h");
    expect(waitLabel(ago(3 * 86_400_000), now)).toBe("waiting 3 d");
  });

  it("treats a time in the future as just now", () => {
    expect(waitLabel(new Date(now + 60_000).toISOString(), now)).toBe("just now");
  });

  it("returns null without a valid time", () => {
    expect(waitLabel(null, now)).toBeNull();
    expect(waitLabel("not a date", now)).toBeNull();
  });
});

describe("flagHint", () => {
  const flag = (targetType: "message" | "draft", layer: string | null, category: string | null, detail: string | null = null) => ({
    targetType,
    layer,
    category,
    detail,
  });

  it("names a flag on the message and says to tick the review box", () => {
    expect(flagHint([flag("message", "policy", "safety_concern")])).toBe(
      "Safety concern on the message. Tick “I've reviewed this”, then answer.",
    );
  });

  it("asks her to check the AI draft when the flag is on the draft", () => {
    expect(flagHint([flag("draft", "moderation", "harassment")])).toBe(
      "Harassing language on the AI draft. Check the draft, tick “I've reviewed this”, then answer.",
    );
  });

  it("names the first flag and counts the rest", () => {
    expect(flagHint([flag("message", "policy", "safety_concern"), flag("draft", "moderation", "harassment")])).toBe(
      "Safety concern and 1 more flag. Open it to review each one, then answer.",
    );
    expect(
      flagHint([flag("message", null, null), flag("draft", null, null), flag("draft", null, null)]),
    ).toBe("Flagged and 2 more flags. Open it to review each one, then answer.");
  });

  it("falls back to the general sentence when no flag details are known", () => {
    expect(flagHint([])).toBe("A safety check flagged this. Review it before answering.");
  });
});
