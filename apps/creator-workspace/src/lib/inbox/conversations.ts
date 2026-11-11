// Pure helpers for the inbox chat rail (UI v2 spec, requirement 8). No Supabase here.
import type { InboxMessage } from "./queries";

export type ConversationSummary = {
  followerId: string;
  username: string | null;
  /** Text of the follower's newest message; null when it was attachment-only. */
  lastText: string | null;
  lastAt: string;
  count: number;
};

/** One row per follower, the conversation with the newest message first. Input order doesn't matter. */
export function groupConversations(messages: readonly InboxMessage[]): ConversationSummary[] {
  const byFollower = new Map<string, ConversationSummary>();
  for (const message of messages) {
    const existing = byFollower.get(message.follower.id);
    if (!existing) {
      byFollower.set(message.follower.id, {
        followerId: message.follower.id,
        username: message.follower.username,
        lastText: message.text,
        lastAt: message.receivedAt,
        count: 1,
      });
      continue;
    }
    existing.count += 1;
    if (Date.parse(message.receivedAt) > Date.parse(existing.lastAt)) {
      existing.lastText = message.text;
      existing.lastAt = message.receivedAt;
    }
  }
  return [...byFollower.values()].sort((a, b) => Date.parse(b.lastAt) - Date.parse(a.lastAt));
}

/** Which list the rail shows for a route: conversations, inbox questions, or none (rail hidden). */
export function railModeFor(pathname: string): "chats" | "questions" | null {
  if (/^\/inbox\/question\/[^/]+\/?$/.test(pathname)) return "questions";
  if (/^\/inbox\/(?!question\/?$)[^/]+\/?$/.test(pathname)) return "chats";
  return null;
}

/** Compact age for rail rows: "now", "5m", "3h", "2d", "2w". Empty for an unreadable timestamp. */
export function shortAgo(iso: string, now: number = Date.now()): string {
  const at = Date.parse(iso);
  if (Number.isNaN(at)) return "";
  const minutes = Math.floor(Math.max(0, now - at) / 60_000);
  if (minutes < 1) return "now";
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.floor(hours / 24);
  return days < 7 ? `${days}d` : `${Math.floor(days / 7)}w`;
}
