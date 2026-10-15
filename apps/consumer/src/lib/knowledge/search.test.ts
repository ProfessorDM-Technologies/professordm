import { describe, expect, it } from "vitest";
import { entryExcerpt, entryTitle, filterEntries, popularTopics, searchTerms, type KnowledgeEntry } from "./search";

const entries: KnowledgeEntry[] = [
  {
    id: "1",
    title: "Why are the lower leaves on my pothos turning yellow?",
    content: "Usually too much water. Let the soil dry out.",
    tags: ["yellow leaves", "overwatering"],
  },
  {
    id: "2",
    title: "How do I get rid of fungus gnats?",
    content: "Let the top of the soil dry and use sticky traps.",
    tags: ["fungus gnats", "pests"],
  },
  {
    id: "3",
    title: "There are tiny webs on my plant",
    content: "Spider mites. Rinse and spray with insecticidal soap.",
    tags: ["pests"],
  },
  { id: "4", title: null, content: null, tags: null },
];

describe("searchTerms", () => {
  it("lowercases and splits on whitespace", () => {
    expect(searchTerms("  Fungus   GNATS ")).toEqual(["fungus", "gnats"]);
    expect(searchTerms("   ")).toEqual([]);
  });
});

describe("filterEntries", () => {
  it("returns everything for an empty query", () => {
    expect(filterEntries(entries, "")).toHaveLength(4);
    expect(filterEntries(entries, "   ")).toHaveLength(4);
  });

  it("matches the title, ignoring case", () => {
    expect(filterEntries(entries, "POTHOS").map((e) => e.id)).toEqual(["1"]);
  });

  it("matches the content", () => {
    expect(filterEntries(entries, "insecticidal").map((e) => e.id)).toEqual(["3"]);
  });

  it("matches tags", () => {
    expect(filterEntries(entries, "pests").map((e) => e.id)).toEqual(["2", "3"]);
    expect(filterEntries(entries, "overwatering").map((e) => e.id)).toEqual(["1"]);
  });

  it("requires every word to match", () => {
    expect(filterEntries(entries, "soil traps").map((e) => e.id)).toEqual(["2"]);
    expect(filterEntries(entries, "soil mites")).toEqual([]);
  });

  it("returns nothing when no entry matches", () => {
    expect(filterEntries(entries, "orchid")).toEqual([]);
  });

  it("treats regex characters as plain text", () => {
    expect(filterEntries(entries, ".*")).toEqual([]);
  });
});

describe("popularTopics", () => {
  it("orders tags by how many entries use them, then alphabetically", () => {
    expect(popularTopics(entries)).toEqual(["pests", "fungus gnats", "overwatering", "yellow leaves"]);
  });

  it("respects the limit", () => {
    expect(popularTopics(entries, 2)).toEqual(["pests", "fungus gnats"]);
  });

  it("counts a tag once per entry and normalizes case and spaces", () => {
    const duplicated: KnowledgeEntry[] = [{ id: "a", title: null, content: null, tags: ["Pests", " pests ", ""] }];
    expect(popularTopics(duplicated)).toEqual(["pests"]);
  });
});

describe("entryTitle", () => {
  it("uses the title when there is one", () => {
    expect(entryTitle(entries[0])).toBe("Why are the lower leaves on my pothos turning yellow?");
  });

  it("falls back to the first line of the content", () => {
    expect(entryTitle({ id: "x", title: "  ", content: "First line\nSecond line", tags: [] })).toBe("First line");
  });

  it("falls back to a default when there is nothing", () => {
    expect(entryTitle(entries[3])).toBe("Untitled answer");
  });
});

describe("entryExcerpt", () => {
  it("collapses whitespace and shortens long text", () => {
    expect(entryExcerpt("a\n\nb   c")).toBe("a b c");
    const excerpt = entryExcerpt("word ".repeat(100), 20);
    expect(excerpt.length).toBeLessThanOrEqual(20);
    expect(excerpt.endsWith("…")).toBe(true);
  });

  it("handles missing content", () => {
    expect(entryExcerpt(null)).toBe("");
  });
});
