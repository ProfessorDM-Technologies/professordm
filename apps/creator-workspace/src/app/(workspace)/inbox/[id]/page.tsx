import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { Avatar } from "@/components/inbox/avatar";
import { ConversationList } from "@/components/inbox/conversation-list";
import { RealtimeRefresh } from "@/components/inbox/realtime-refresh";
import { ReplyBox } from "@/components/inbox/reply-box";
import { LocalTime } from "@/components/local-time";
import { RefreshButton } from "@/components/refresh-button";
import { conversationsFromThreads } from "@/lib/inbox/conversations";
import { outboundStatusLabel, outboundTypeLabel } from "@/lib/inbox/labels";
import { getThread, listInboundThreads } from "@/lib/inbox/queries";
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
    <li className={`flex ${outgoing ? "justify-end" : "justify-start"}`}>
      <div
        className={`flex max-w-[85%] flex-col space-y-1 sm:max-w-[70%] ${outgoing ? "items-end text-right" : "items-start"}`}
      >
        <p className="sr-only">{outgoing ? "You sent:" : "They sent:"}</p>
        <div
          className={`whitespace-pre-wrap rounded-3xl px-4 py-2.5 text-left text-[0.9375rem] leading-snug ${
            outgoing ? "rounded-br-lg bg-pdm-accent text-pdm-on-accent" : "rounded-bl-lg bg-pdm-subtle text-pdm-ink"
          }`}
        >
          {item.text || "(Attachment only)"}
        </div>
        <p className="space-x-2 px-1 text-xs text-pdm-muted">
          {caption ? <span>{caption}</span> : null}
          {item.time ? <LocalTime value={item.time} /> : null}
        </p>
      </div>
    </li>
  );
}

// Instagram-style two panes (md and up): every sender on the left, this conversation on the right. The panes have
// a fixed height, so only the message list scrolls and the composer stays put. Phones show the conversation alone.
export default async function ConversationPage({ params }: PageProps<"/inbox/[id]">) {
  const { id } = await params;
  const [thread, inbound] = await Promise.all([getThread(id), listInboundThreads()]);

  if (!thread.found) {
    notFound();
  }

  const username = thread.follower.username ? `@${thread.follower.username}` : "Unknown sender";
  const conversations = conversationsFromThreads(inbound.threads);

  return (
    <div className="flex h-[calc(100dvh-14rem)] min-h-[26rem] overflow-hidden rounded-3xl border border-pdm-border bg-pdm-panel xl:h-[calc(100dvh-12rem)]">
      <RealtimeRefresh />

      <aside className="hidden w-80 shrink-0 border-r border-pdm-border md:flex md:flex-col">
        <ConversationList conversations={conversations} activeId={thread.follower.id} error={inbound.error} now={inbound.loadedAt} />
      </aside>

      <article aria-labelledby="conversation-heading" className="flex min-w-0 flex-1 flex-col">
        <header className="flex items-center gap-3 border-b border-pdm-border px-3 py-3 sm:px-4">
          <Link
            href="/incoming"
            aria-label="Back to all messages"
            className="pdm-press grid size-10 shrink-0 place-items-center rounded-full text-pdm-ink hover:bg-pdm-subtle md:hidden"
          >
            <svg aria-hidden="true" viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M15 5l-7 7 7 7" />
            </svg>
          </Link>
          <Avatar username={thread.follower.username} size="sm" />
          <div className="min-w-0 flex-1">
            <h1 id="conversation-heading" className="truncate text-base font-bold">
              {username}
            </h1>
            <p className="text-xs text-pdm-muted">Instagram conversation</p>
          </div>
          <RefreshButton />
        </header>

        {thread.error ? (
          <p role="alert" className="border-b border-pdm-danger-line bg-pdm-danger-bg px-4 py-2 text-sm font-medium text-pdm-danger-ink">
            Part of this conversation couldn&apos;t be loaded. Try again.
          </p>
        ) : null}

        {/* column-reverse keeps the scroll pinned to the newest message without any script. */}
        <div
          tabIndex={0}
          aria-label={`Messages with ${username}`}
          className="flex min-h-0 flex-1 flex-col-reverse overflow-y-auto overscroll-contain px-3 py-4 outline-none focus-visible:ring-2 focus-visible:ring-pdm-accent focus-visible:ring-inset sm:px-5"
        >
          {thread.items.length === 0 ? (
            <p className="m-auto text-sm text-pdm-muted">No messages in this conversation yet.</p>
          ) : (
            <ol className="space-y-3">
              {thread.items.map((item) => (
                <Bubble key={item.key} item={item} />
              ))}
            </ol>
          )}
        </div>

        {thread.latestInboundId ? (
          <ReplyBox inboundMessageId={thread.latestInboundId} recipient={username} />
        ) : (
          <p className="border-t border-pdm-border px-4 py-3 text-sm text-pdm-muted">
            You can reply once {username} has sent you a message.
          </p>
        )}
      </article>
    </div>
  );
}
