import { describe, expect, it } from "vitest";
import {
  changeRatio,
  checkSendGate,
  nextRequestId,
  normalizeAnswer,
  parseAnswer,
  parseTags,
  type GateInput,
  type SendOutcome,
} from "./answer";

const QUESTION_ID = "6f1c2a9e-1b2c-4d3e-8f90-112233445566";
const INBOUND_ID = "7a2b3c4d-1b2c-4d3e-8f90-112233445566";
const REQUEST_ID = "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d";
const FLAG_ID = "b1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d";

const AI_TEXT = "Move it away from the window and water when the top inch is dry.";

describe("normalizeAnswer", () => {
  it("collapses spaces and trims", () => {
    expect(normalizeAnswer("  Water   twice a week.  ")).toBe("Water twice a week.");
  });

  it("treats line breaks and tabs as spaces", () => {
    expect(normalizeAnswer("Water\n\ntwice\ta week.\r\n")).toBe("Water twice a week.");
  });
});

describe("changeRatio", () => {
  it("is 0 for identical text, even with different spacing", () => {
    expect(changeRatio(AI_TEXT, AI_TEXT)).toBe(0);
    expect(changeRatio(AI_TEXT, `  ${AI_TEXT.replaceAll(" ", "\n")} `)).toBe(0);
  });

  it("is 1 when every word is new", () => {
    expect(changeRatio("water less often", "repot into chunky mix")).toBe(1);
    expect(changeRatio(AI_TEXT, "")).toBe(1);
  });

  it("is between 0 and 1 for a partial edit", () => {
    // 4 of 4 words kept, 4 words added: 1 - 4/8.
    expect(changeRatio("water when it's dry", "water when it's dry or about once weekly")).toBeCloseTo(0.5);
    const edited = changeRatio(AI_TEXT, AI_TEXT.replace("the top inch", "the top two inches"));
    expect(edited).toBeGreaterThan(0);
    expect(edited).toBeLessThan(0.3);
  });

  it("is 0 when both are empty", () => {
    expect(changeRatio("", "  ")).toBe(0);
  });
});

describe("parseTags", () => {
  it("trims, lower-cases and drops empty entries", () => {
    expect(parseTags(["  Calathea ", "", "  "])).toEqual({ ok: true, tags: ["calathea"] });
  });

  it("splits comma-separated input", () => {
    expect(parseTags("Calathea, watering ,,Light")).toEqual({ ok: true, tags: ["calathea", "watering", "light"] });
  });

  it("removes duplicates after lower-casing", () => {
    expect(parseTags(["Calathea", "calathea", " CALATHEA "])).toEqual({ ok: true, tags: ["calathea"] });
  });

  it("allows 5 tags and rejects 6", () => {
    expect(parseTags(["a", "b", "c", "d", "e"])).toEqual({ ok: true, tags: ["a", "b", "c", "d", "e"] });
    expect(parseTags(["a", "b", "c", "d", "e", "f"])).toEqual({ ok: false, error: "Use at most 5 tags." });
  });

  it("allows 40 characters and rejects 41", () => {
    expect(parseTags(["x".repeat(40)]).ok).toBe(true);
    expect(parseTags(["x".repeat(41)])).toEqual({ ok: false, error: "Keep each tag to 40 characters or fewer." });
  });

  it("ignores values that aren't strings", () => {
    expect(parseTags([null, 3, "pothos"])).toEqual({ ok: true, tags: ["pothos"] });
  });
});

describe("checkSendGate", () => {
  const passing: GateInput = {
    text: `${AI_TEXT} Mist it in the morning.`,
    aiText: AI_TEXT,
    tags: ["calathea"],
    openFlagIds: [FLAG_ID],
    acknowledgedFlagIds: [FLAG_ID],
  };
  const codes = (input: GateInput) => checkSendGate(input).missing.map((issue) => issue.code);

  it("passes when every rule is met", () => {
    expect(checkSendGate(passing)).toEqual({ ok: true, missing: [] });
  });

  it("needs text", () => {
    expect(codes({ ...passing, text: "  \n " })).toEqual(["text_required"]);
  });

  it("blocks text over the character limit", () => {
    expect(codes({ ...passing, text: "a".repeat(999) })).toEqual([]);
    expect(codes({ ...passing, text: "a".repeat(1000) })).toEqual(["text_too_long"]);
  });

  it("counts UTF-8 bytes for emoji and accented text", () => {
    expect(codes({ ...passing, text: "🌱".repeat(250) })).toEqual([]);
    expect(codes({ ...passing, text: "🌱".repeat(251) })).toEqual(["text_too_long"]);
    expect(codes({ ...passing, text: "é".repeat(500) })).toEqual([]);
    expect(codes({ ...passing, text: "é".repeat(501) })).toEqual(["text_too_long"]);
  });

  it("needs an edit when there was an AI draft, ignoring spacing", () => {
    expect(codes({ ...passing, text: AI_TEXT })).toEqual(["edit_required"]);
    expect(codes({ ...passing, text: `\n${AI_TEXT.replaceAll(" ", "  ")}  ` })).toEqual(["edit_required"]);
  });

  it("skips the edit rule when there was no AI draft", () => {
    expect(codes({ ...passing, aiText: null, text: "My own answer." })).toEqual([]);
  });

  it("needs at least one tag", () => {
    expect(checkSendGate({ ...passing, tags: [] }).missing).toEqual([
      { code: "tags_required", message: "Add at least one tag" },
    ]);
  });

  it("rejects too many tags", () => {
    expect(codes({ ...passing, tags: ["a", "b", "c", "d", "e", "f"] })).toEqual(["tags_invalid"]);
  });

  it("needs every open flag acknowledged", () => {
    expect(codes({ ...passing, acknowledgedFlagIds: [] })).toEqual(["flags_unreviewed"]);
    expect(codes({ ...passing, openFlagIds: [FLAG_ID, REQUEST_ID], acknowledgedFlagIds: [FLAG_ID] })).toEqual([
      "flags_unreviewed",
    ]);
    expect(codes({ ...passing, openFlagIds: [], acknowledgedFlagIds: [] })).toEqual([]);
  });

  it("lists everything that is missing, in order", () => {
    expect(checkSendGate({ ...passing, text: AI_TEXT, tags: [], acknowledgedFlagIds: [] }).missing).toEqual([
      { code: "edit_required", message: "Edit the draft so it's in your words" },
      { code: "tags_required", message: "Add at least one tag" },
      { code: "flags_unreviewed", message: "Review the safety flags" },
    ]);
  });
});

describe("parseAnswer", () => {
  const fields = (overrides: Partial<Parameters<typeof parseAnswer>[0]> = {}) => ({
    text: "  My answer.  ",
    questionId: QUESTION_ID,
    inboundMessageId: INBOUND_ID,
    clientRequestId: REQUEST_ID,
    tags: ["Calathea"],
    reviewedFlagIds: [FLAG_ID, FLAG_ID],
    ...overrides,
  });

  it("accepts a valid answer, trims text, cleans tags and dedupes flag ids", () => {
    expect(parseAnswer(fields())).toEqual({
      ok: true,
      answer: {
        text: "My answer.",
        questionId: QUESTION_ID,
        inboundMessageId: INBOUND_ID,
        clientRequestId: REQUEST_ID,
        tags: ["calathea"],
        reviewedFlagIds: [FLAG_ID],
      },
    });
  });

  it("returns typed errors", () => {
    const code = (overrides: Partial<Parameters<typeof parseAnswer>[0]>) => {
      const result = parseAnswer(fields(overrides));
      return result.ok ? null : result.error.code;
    };
    expect(code({ text: "   " })).toBe("text_required");
    expect(code({ text: "🌱".repeat(251) })).toBe("text_too_long");
    expect(code({ tags: [] })).toBe("tags_required");
    expect(code({ tags: ["x".repeat(41)] })).toBe("tags_invalid");
    expect(code({ questionId: "not-a-uuid" })).toBe("invalid_request");
    expect(code({ clientRequestId: null })).toBe("invalid_request");
    expect(code({ reviewedFlagIds: ["nope"] })).toBe("invalid_request");
  });
});

describe("nextRequestId", () => {
  const fresh = () => "new-id";
  const next = (outcome: SendOutcome) => nextRequestId("old-id", outcome, fresh);

  it("makes a new id after success", () => {
    expect(next({ kind: "response", httpStatus: 200, deliveryStatus: "sent" })).toBe("new-id");
  });

  it("makes a new id after every 4xx", () => {
    for (const httpStatus of [400, 401, 403, 404, 409, 422, 429]) {
      expect(next({ kind: "response", httpStatus })).toBe("new-id");
    }
  });

  it("makes a new id after 502 delivery_failed", () => {
    expect(next({ kind: "response", httpStatus: 502, error: "delivery_failed" })).toBe("new-id");
  });

  it("makes a new id when a repeated request returns a failed row", () => {
    expect(next({ kind: "response", httpStatus: 200, deliveryStatus: "failed" })).toBe("new-id");
  });

  it("keeps the id after a network error or timeout", () => {
    expect(next({ kind: "network_error" })).toBe("old-id");
    expect(next({ kind: "timeout" })).toBe("old-id");
  });

  it("keeps the id after 500, 503 and a 502 without delivery_failed", () => {
    expect(next({ kind: "response", httpStatus: 500 })).toBe("old-id");
    expect(next({ kind: "response", httpStatus: 503 })).toBe("old-id");
    expect(next({ kind: "response", httpStatus: 502 })).toBe("old-id");
  });

  it("keeps the id while the send is still pending", () => {
    expect(next({ kind: "response", httpStatus: 200, deliveryStatus: "pending" })).toBe("old-id");
  });

  it("uses crypto.randomUUID by default", () => {
    expect(nextRequestId("old-id", { kind: "response", httpStatus: 200 })).toMatch(/^[0-9a-f-]{36}$/);
  });
});
