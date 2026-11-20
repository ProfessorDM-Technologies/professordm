import { describe, expect, it } from "vitest";
import { conversationsFromThreads } from "./conversations";
import type { MessageThread } from "./message-threads";
import type { InboxMessage } from "./queries";

function message(id: string, followerId: string, receivedAt: string, text: string | null = id): InboxMessage {
  return {
    id,
    text,
    category: null,
    overridden: false,
    confidence: null,
    status: null,
    receivedAt,
    follower: { id: followerId, username: `user_${followerId}` },
  };
}

function thread(head: InboxMessage, replies: InboxMessage[] = []): MessageThread<InboxMessage> {
  const latestAt = [head, ...replies].map((m) => m.receivedAt).sort().at(-1)!;
  return { head, replies, latestAt };
}

describe("conversationsFromThreads", () => {
  it("keeps one row per sender, from their newest thread", () => {
    const rows = conversationsFromThreads([
      thread(message("a1", "a", "2026-11-01T10:00:00Z", "old question")),
      thread(message("a2", "a", "2026-11-03T10:00:00Z", "new question")),
    ]);
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ followerId: "a", preview: "new question", latestAt: "2026-11-03T10:00:00Z" });
  });

  it("previews the newest clarification reply over the question", () => {
    const rows = conversationsFromThreads([
      thread(message("q", "a", "2026-11-01T10:00:00Z", "question"), [message("r", "a", "2026-11-01T11:00:00Z", "reply")]),
    ]);
    expect(rows[0].preview).toBe("reply");
  });

  it("sorts senders newest first", () => {
    const rows = conversationsFromThreads([
      thread(message("a1", "a", "2026-11-01T10:00:00Z")),
      thread(message("b1", "b", "2026-11-05T10:00:00Z")),
      thread(message("c1", "c", "2026-11-03T10:00:00Z")),
    ]);
    expect(rows.map((row) => row.followerId)).toEqual(["b", "c", "a"]);
  });

  it("returns nothing for no threads", () => {
    expect(conversationsFromThreads([])).toEqual([]);
  });
});
