import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";
import { ReplyBox } from "@/components/inbox/reply-box";
import { LocalTime } from "@/components/local-time";
import { Placeholder } from "@/components/placeholder";
import { RefreshButton } from "@/components/refresh-button";
import { outboundStatusLabel, outboundTypeLabel } from "@/lib/inbox/labels";
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
    <li className={`flex ${outgoing ? "justify-end" : "justify-start"}`}>
      <div
        className={`flex max-w-[85%] flex-col space-y-1 sm:max-w-[70%] ${outgoing ? "items-end text-right" : "items-start"}`}
      >
        <p className="sr-only">{outgoing ? "You sent:" : "They sent:"}</p>
        <div
          className={`whitespace-pre-wrap rounded-2xl px-4 py-2 text-left text-sm ${
            outgoing ? "bg-pdm-accent text-white" : "border border-pdm-border bg-white text-pdm-ink"
          }`}
        >
          {item.text || "(No text — attachment only)"}
        </div>
        <p className="space-x-2 text-xs text-pdm-muted">
          {caption ? <span>{caption}</span> : null}
          {item.time ? <LocalTime value={item.time} /> : null}
        </p>
      </div>
    </li>
  );
}

export default async function ConversationPage({ params }: PageProps<"/inbox/[id]">) {
  const { id } = await params;
  const thread = await getThread(id);

  if (!thread.found) {
    notFound();
  }

  const username = thread.follower.username ? `@${thread.follower.username}` : "Unknown sender";

  return (
    <article className="space-y-6">
      <p>
        <Link href="/inbox" className="text-sm font-medium text-pdm-accent-strong underline underline-offset-4">
          Back to inbox
        </Link>
      </p>

      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="space-y-1">
          <h1 className="text-2xl font-semibold tracking-tight">{username}</h1>
          <p className="text-pdm-muted">Instagram conversation</p>
        </div>
        <RefreshButton />
      </div>

      {thread.error ? (
        <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm font-medium text-red-800">
          Part of this conversation couldn&apos;t be loaded. Try again.
        </p>
      ) : null}

      {thread.items.length === 0 ? (
        <Placeholder>No messages in this conversation yet.</Placeholder>
      ) : (
        <ol aria-label={`Messages with ${username}`} className="space-y-4">
          {thread.items.map((item) => (
            <Bubble key={item.key} item={item} />
          ))}
        </ol>
      )}

      {thread.latestInboundId ? (
        <ReplyBox inboundMessageId={thread.latestInboundId} recipient={username} />
      ) : null}
    </article>
  );
}
