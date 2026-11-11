import type { Metadata } from "next";
import { LiveItem, LiveList } from "@/components/ui/live-list";
import { notFound } from "next/navigation";
import { ConversationProvider, MessagePane } from "@/components/inbox/message-pane";
import { ReplyBox } from "@/components/inbox/reply-box";
import { RealtimeRefresh } from "@/components/inbox/realtime-refresh";
import { LocalTime } from "@/components/local-time";
import { Placeholder } from "@/components/placeholder";
import { RefreshButton } from "@/components/refresh-button";
import { isCreatorAuthored, outboundStatusLabel, outboundTypeLabel } from "@/lib/inbox/labels";
import { getThread } from "@/lib/inbox/queries";
import type { ThreadItem } from "@/lib/inbox/thread";

export const metadata: Metadata = {
  title: "Conversation",
};

function itemCaption(item: ThreadItem) {
  if (item.kind === "clarification_prompt") return "Clarification question";
  if (item.kind === "clarification_reply") return "Reply to clarification";
  if (item.kind === "outbound" && item.outboundType) {
    const status = outboundStatusLabel(item.status);
    return status ? `${outboundTypeLabel(item.outboundType)} · ${status}` : outboundTypeLabel(item.outboundType);
  }
  return null;
}

function Bubble({ item }: { item: ThreadItem }) {
  const outgoing = item.direction === "out";
  const caption = itemCaption(item);

  return (
    <LiveItem className={`flex ${outgoing ? "justify-end" : "justify-start"}`}>
      <div
        className={`flex max-w-[85%] flex-col space-y-1 sm:max-w-[70%] ${outgoing ? "items-end text-right" : "items-start"}`}
      >
        <p className="sr-only">{outgoing ? "You sent:" : "They sent:"}</p>
        <div
          className={`whitespace-pre-wrap rounded-xl px-4 py-2 text-left text-sm text-pdm-ink ${
            // Spec section 3.1: the creator's own words on Soft Sage, automated messages on AI cyan, the follower's on white.
            !outgoing
              ? "bg-pdm-bubble-in ring-1 ring-pdm-border"
              : isCreatorAuthored(item.outboundType)
                ? "bg-pdm-bubble-human ring-1 ring-pdm-success/25"
                : "bg-pdm-bubble-ai ring-1 ring-pdm-ai/25"
          }`}
        >
          {item.text || "(No text — attachment only)"}
        </div>
        <p className="space-x-2 text-xs text-pdm-muted">
          {caption ? <span>{caption}</span> : null}
          {item.time ? <LocalTime value={item.time} /> : null}
        </p>
      </div>
    </LiveItem>
  );
}

export default async function ConversationPage({ params }: PageProps<"/inbox/[id]">) {
  const { id } = await params;
  const thread = await getThread(id);

  if (!thread.found) {
    notFound();
  }

  const username = thread.follower.username ? `@${thread.follower.username}` : "Unknown sender";

  // A fixed-height pane: header and reply box stay put, only the messages scroll (UI v2 spec, requirement 4).
  // Heights subtract the island, page padding and (below lg) the "All chats" button / mobile tab island.
  return (
    <article className="flex h-[calc(100dvh-17.25rem)] min-h-[26rem] flex-col overflow-hidden rounded-xl border border-pdm-border bg-pdm-card md:h-[calc(100dvh-13.25rem)] lg:h-[calc(100dvh-10rem)]">
      <RealtimeRefresh />
      <ConversationProvider>
      <header className="flex items-center justify-between gap-3 border-b border-pdm-border px-4 py-3">
        <div className="flex min-w-0 items-center gap-3">
          <span
            aria-hidden="true"
            className="flex size-10 shrink-0 items-center justify-center rounded-full bg-pdm-primary-tint font-display font-bold text-pdm-primary"
          >
            {(thread.follower.username?.[0] ?? "?").toUpperCase()}
          </span>
          <div className="min-w-0">
            <h1 className="truncate text-lg font-bold">{username}</h1>
            <p className="text-xs text-pdm-muted">Instagram conversation</p>
          </div>
        </div>
        <RefreshButton />
      </header>

      {thread.error ? (
        <p role="alert" className="border-b border-pdm-danger-border bg-pdm-danger-tint px-4 py-2 text-sm font-medium text-pdm-danger-text">
          Part of this conversation couldn&apos;t be loaded. Try again.
        </p>
      ) : null}

      <MessagePane count={thread.items.length}>
        {thread.items.length === 0 ? (
          <Placeholder>No messages in this conversation yet.</Placeholder>
        ) : (
          <LiveList as="ol" aria-label={`Messages with ${username}`} className="space-y-4">
            {thread.items.map((item) => (
              <Bubble key={item.key} item={item} />
            ))}
          </LiveList>
        )}
      </MessagePane>

      {thread.latestInboundId ? (
        <ReplyBox inboundMessageId={thread.latestInboundId} recipient={username} />
      ) : (
        <p className="border-t border-pdm-border px-4 py-3 text-sm text-pdm-muted">
          There&apos;s no message from {username} to reply to yet.
        </p>
      )}
      </ConversationProvider>
    </article>
  );
}
