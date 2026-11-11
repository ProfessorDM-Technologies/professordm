import { describe, expect, it } from "vitest";
import { groupConversations, railModeFor, shortAgo } from "./conversations";
import type { InboxMessage } from "./queries";

const msg = (id: string, followerId: string, username: string | null, receivedAt: string, text: string | null = id): InboxMessage => ({
  id,
  text,
  category: null,
  overridden: false,
  confidence: null,
  status: null,
  receivedAt,
  follower: { id: followerId, username },
});

describe("groupConversations", () => {
  it("returns one row per follower, newest conversation first", () => {
    const rows = groupConversations([
      msg("a1", "akshay", "akshayvoora", "2026-11-01T10:00:00Z"),
      msg("c1", "chinmay", "chinmayv1545", "2026-11-03T10:00:00Z"),
      msg("a2", "akshay", "akshayvoora", "2026-11-04T10:00:00Z", "latest from akshay"),
    ]);
    expect(rows.map((row) => row.followerId)).toEqual(["akshay", "chinmay"]);
    expect(rows[0]).toMatchObject({ username: "akshayvoora", lastText: "latest from akshay", lastAt: "2026-11-04T10:00:00Z", count: 2 });
    expect(rows[1].count).toBe(1);
  });

  it("does not depend on input order", () => {
    const rows = groupConversations([
      msg("old", "k", "karthik", "2026-11-01T00:00:00Z", "old"),
      msg("new", "k", "karthik", "2026-11-02T00:00:00Z", "new"),
    ]);
    expect(rows[0].lastText).toBe("new");
  });

  it("keeps a missing username and attachment-only text as null", () => {
    const [row] = groupConversations([msg("x", "f", null, "2026-11-01T00:00:00Z", null)]);
    expect(row.username).toBeNull();
    expect(row.lastText).toBeNull();
  });

  it("is empty for no messages", () => {
    expect(groupConversations([])).toEqual([]);
  });
});

describe("railModeFor", () => {
  it("shows chats on a conversation", () => {
    expect(railModeFor("/inbox/1d71453f-4414-4129-a662-bfc8e0112cc5")).toBe("chats");
  });

  it("shows questions on the answer screen", () => {
    expect(railModeFor("/inbox/question/693b1e5f")).toBe("questions");
  });

  it("hides on list pages and elsewhere", () => {
    expect(railModeFor("/inbox")).toBeNull();
    expect(railModeFor("/inbox/")).toBeNull();
    expect(railModeFor("/sent")).toBeNull();
    expect(railModeFor("/inbox/question")).toBeNull();
  });
});

describe("shortAgo", () => {
  const now = Date.parse("2026-11-11T12:00:00Z");
  const ago = (ms: number) => new Date(now - ms).toISOString();

  it("uses compact units for the rail", () => {
    expect(shortAgo(ago(20_000), now)).toBe("now");
    expect(shortAgo(ago(5 * 60_000), now)).toBe("5m");
    expect(shortAgo(ago(3 * 3_600_000), now)).toBe("3h");
    expect(shortAgo(ago(2 * 86_400_000), now)).toBe("2d");
    expect(shortAgo(ago(15 * 86_400_000), now)).toBe("2w");
  });

  it("treats future and invalid times safely", () => {
    expect(shortAgo(ago(-60_000), now)).toBe("now");
    expect(shortAgo("not a date", now)).toBe("");
  });
});
