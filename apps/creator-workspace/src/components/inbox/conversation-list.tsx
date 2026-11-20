import Link from "next/link";
import { Avatar } from "@/components/inbox/avatar";
import { ShortTime } from "@/components/short-time";
import type { ConversationSummary } from "@/lib/inbox/conversations";

// Left rail of the conversation page: every sender, newest first, with the open one highlighted.
export function ConversationList({
  conversations,
  activeId,
  error,
  now,
}: {
  conversations: ConversationSummary[];
  activeId: string;
  error: boolean;
  now: number;
}) {
  return (
    <nav aria-label="Conversations" className="flex min-h-0 flex-col">
      <div className="flex items-baseline justify-between px-4 pt-4 pb-3">
        <h2 className="text-lg font-bold">Messages</h2>
        <Link href="/incoming" className="text-sm font-semibold text-pdm-accent-strong underline underline-offset-4">
          See all
        </Link>
      </div>

      {error ? (
        <p role="alert" className="px-4 text-sm text-pdm-danger-ink">
          Couldn&apos;t load your other conversations.
        </p>
      ) : conversations.length === 0 ? (
        <p className="px-4 text-sm text-pdm-muted">No other conversations yet.</p>
      ) : (
        <ul className="min-h-0 flex-1 space-y-0.5 overflow-y-auto px-2 pb-2">
          {conversations.map((conversation) => {
            const active = conversation.followerId === activeId;
            const name = conversation.username ? `@${conversation.username}` : "Unknown sender";
            return (
              <li key={conversation.followerId}>
                <Link
                  href={`/inbox/${conversation.followerId}`}
                  aria-current={active ? "page" : undefined}
                  className={`pdm-press flex items-center gap-3 rounded-2xl px-2.5 py-2.5 ${
                    active ? "bg-pdm-tint" : "hover:bg-pdm-subtle"
                  }`}
                >
                  <Avatar username={conversation.username} />
                  <span className="min-w-0 flex-1">
                    <span className="flex items-baseline justify-between gap-2">
                      <span className={`truncate text-sm ${active ? "font-bold text-pdm-heading" : "font-semibold"}`}>
                        {name}
                      </span>
                      <ShortTime value={conversation.latestAt} now={now} className="shrink-0 text-xs text-pdm-muted" />
                    </span>
                    <span className="block truncate text-sm text-pdm-muted">
                      {conversation.preview || "Attachment"}
                    </span>
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </nav>
  );
}
