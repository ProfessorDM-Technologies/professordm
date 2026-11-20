// Pure: the left-hand conversation list on the conversation page (Instagram-style). One row per sender,
// newest activity first. No Supabase here so it can be unit tested.
import type { MessageThread } from "./message-threads";
import type { InboxMessage } from "./queries";

export type ConversationSummary = {
  followerId: string;
  username: string | null;
  /** The newest text from this sender, for the one-line preview. */
  preview: string | null;
  latestAt: string;
};

function toTime(value: string): number {
  const time = Date.parse(value);
  return Number.isNaN(time) ? -Infinity : time;
}

export function conversationsFromThreads(threads: readonly MessageThread<InboxMessage>[]): ConversationSummary[] {
  const bySender = new Map<string, ConversationSummary>();

  for (const thread of threads) {
    const latest = thread.replies.at(-1) ?? thread.head;
    const followerId = thread.head.follower.id;
    const existing = bySender.get(followerId);
    if (existing && toTime(existing.latestAt) >= toTime(thread.latestAt)) continue;
    bySender.set(followerId, {
      followerId,
      username: thread.head.follower.username,
      preview: latest.text,
      latestAt: thread.latestAt,
    });
  }

  return [...bySender.values()].sort((a, b) => toTime(b.latestAt) - toTime(a.latestAt));
}
