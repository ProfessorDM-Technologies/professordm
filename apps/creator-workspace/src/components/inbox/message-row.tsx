import Link from "next/link";
import { LocalTime } from "@/components/local-time";
import { categoryLabel, inboundStatusLabel } from "@/lib/inbox/labels";
import type { MessageThread } from "@/lib/inbox/message-threads";
import type { InboxMessage } from "@/lib/inbox/queries";

const CATEGORY_STYLES: Record<string, string> = {
  expert_question: "bg-pdm-tint text-pdm-accent-strong",
  safety_concern: "bg-pdm-danger-bg text-pdm-danger-ink",
  spam_irrelevant: "bg-pdm-subtle text-pdm-muted",
};

// One row per question thread (SCRUM-144): the question DM, its labels and status, and a line for the
// clarification replies folded under it. The time is the thread's latest activity, like an email inbox.
export function MessageRow({ thread }: { thread: MessageThread<InboxMessage> }) {
  const { head: message, replies, latestAt } = thread;
  const username = message.follower.username ? `@${message.follower.username}` : "Unknown sender";
  const status = inboundStatusLabel(message.status);
  const badgeStyle = (message.category && CATEGORY_STYLES[message.category]) ?? "bg-pdm-subtle text-pdm-ink";
  const latestReply = replies.at(-1);

  return (
    <li>
      <Link
        href={`/inbox/${message.follower.id}`}
        className="block space-y-2 rounded-lg border border-pdm-border bg-pdm-panel p-4 hover:border-pdm-accent"
      >
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
          <p className="font-semibold">{username}</p>
          <LocalTime value={latestAt} className="text-xs text-pdm-muted" />
        </div>

        <p className="line-clamp-2 text-sm text-pdm-ink">{message.text || "(No text — attachment only)"}</p>

        {latestReply ? (
          <p className="line-clamp-1 border-l-2 border-pdm-border pl-3 text-sm text-pdm-muted">
            <span className="font-medium text-pdm-ink">
              {replies.length === 1 ? "1 reply" : `${replies.length} replies`}
            </span>
            {" · "}
            {latestReply.text || "(No text — attachment only)"}
          </p>
        ) : null}

        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className={`rounded-full px-2 py-0.5 font-semibold ${badgeStyle}`}>{categoryLabel(message.category)}</span>
          {message.overridden ? <span className="text-pdm-muted">Label changed by you</span> : null}
          {message.confidence !== null && !message.overridden ? (
            <span className="text-pdm-muted">{Math.round(message.confidence * 100)}% confident</span>
          ) : null}
          {status ? <span className="text-pdm-muted">· {status}</span> : null}
        </div>
      </Link>
    </li>
  );
}
