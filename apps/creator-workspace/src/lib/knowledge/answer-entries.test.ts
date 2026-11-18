import { describe, expect, it } from "vitest";
import { PUBLISH_MESSAGES, entryTitle, parsePublish, publishErrorMessage, sortAnswerEntries } from "./answer-entries";

const entryId = "11111111-1111-4111-8111-111111111111";

describe("parsePublish", () => {
  it("reads the entry id and the wanted state", () => {
    expect(parsePublish({ entryId, published: "true" })).toEqual({ ok: true, input: { entryId, published: true } });
    expect(parsePublish({ entryId: entryId.toUpperCase(), published: "false" })).toEqual({
      ok: true,
      input: { entryId, published: false },
    });
  });

  it("rejects anything else", () => {
    expect(parsePublish({ entryId, published: "yes" })).toEqual({ ok: false });
    expect(parsePublish({ entryId, published: null })).toEqual({ ok: false });
    expect(parsePublish({ entryId: "not-a-uuid", published: "true" })).toEqual({ ok: false });
    expect(parsePublish({ entryId: null, published: "true" })).toEqual({ ok: false });
  });
});

describe("publishErrorMessage", () => {
  it("maps the database errors to plain sentences", () => {
    expect(publishErrorMessage({ code: "28000" })).toBe(PUBLISH_MESSAGES.session);
    expect(publishErrorMessage({ code: "P0002" })).toBe(PUBLISH_MESSAGES.unavailable);
    expect(publishErrorMessage({ code: "22023" })).toBe(PUBLISH_MESSAGES.invalid);
    expect(publishErrorMessage({ code: "PGRST202" })).toBe(PUBLISH_MESSAGES.unknown);
  });
});

describe("entryTitle", () => {
  it("uses the title when there is one", () => {
    expect(entryTitle({ title: "  Watering a calathea ", content: "Keep it moist." })).toBe("Watering a calathea");
  });

  it("falls back to the first line of the content", () => {
    expect(entryTitle({ title: null, content: "\nKeep it moist.\nNever soggy." })).toBe("Keep it moist.");
    expect(entryTitle({ title: "  ", content: null })).toBe("Untitled answer");
  });
});

describe("sortAnswerEntries", () => {
  it("puts the newest delivered question first, then entries without one by title", () => {
    const entries = [
      { id: "a", title: "Zebra plant", content: null, deliveredAt: null },
      { id: "b", title: "Old", content: null, deliveredAt: "2026-11-10T10:00:00Z" },
      { id: "c", title: "Aloe", content: null, deliveredAt: null },
      { id: "d", title: "New", content: null, deliveredAt: "2026-11-17T10:00:00Z" },
    ];
    expect(sortAnswerEntries(entries).map((entry) => entry.id)).toEqual(["d", "b", "c", "a"]);
  });
});
