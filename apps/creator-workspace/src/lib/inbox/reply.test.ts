import { describe, expect, it } from "vitest";
import { MAX_REPLY_LENGTH, parseReply } from "./reply";

const INBOUND_ID = "6f1c2a9e-1b2c-4d3e-8f90-112233445566";
const REQUEST_ID = "a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d";

const fields = (text: unknown) => ({ text, inboundMessageId: INBOUND_ID, clientRequestId: REQUEST_ID });

describe("parseReply", () => {
  it("accepts a reply and trims it", () => {
    expect(parseReply(fields("  Water twice a week.  "))).toEqual({
      ok: true,
      reply: { text: "Water twice a week.", inboundMessageId: INBOUND_ID, clientRequestId: REQUEST_ID },
    });
  });

  it("blocks empty and whitespace-only replies", () => {
    for (const text of ["", "   ", "\n\t ", null, undefined]) {
      expect(parseReply(fields(text))).toEqual({ ok: false, error: "Write a reply before sending." });
    }
  });

  it("blocks replies over the Instagram limit", () => {
    expect(parseReply(fields("a".repeat(MAX_REPLY_LENGTH))).ok).toBe(true);
    expect(parseReply(fields("a".repeat(MAX_REPLY_LENGTH + 1))).ok).toBe(false);
  });

  it("enforces the UTF-8 byte limit for emoji and other multibyte text", () => {
    expect(parseReply(fields("🌱".repeat(250))).ok).toBe(true);
    expect(parseReply(fields("🌱".repeat(251))).ok).toBe(false);
    expect(parseReply(fields("é".repeat(501))).ok).toBe(false);
  });

  it("rejects missing or malformed ids", () => {
    expect(parseReply({ text: "Hi", inboundMessageId: "not-a-uuid", clientRequestId: REQUEST_ID }).ok).toBe(false);
    expect(parseReply({ text: "Hi", inboundMessageId: INBOUND_ID, clientRequestId: null }).ok).toBe(false);
  });
});
