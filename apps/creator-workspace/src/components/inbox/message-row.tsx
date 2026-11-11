import Link from "next/link";
import { LiveItem } from "@/components/ui/live-list";
import { cardLinkClass } from "@/components/ui/card-styles";
import { LocalTime } from "@/components/local-time";
import { categoryLabel, inboundStatusLabel } from "@/lib/inbox/labels";
import type { InboxMessage } from "@/lib/inbox/queries";

// AI classification labels: cyan marks questions and AI (spec section 3.1).
const CATEGORY_STYLES: Record<string, string> = {
  expert_question: "bg-pdm-ai-tint text-pdm-ai-text",
  safety_concern: "bg-pdm-danger-tint text-pdm-danger-text",
  spam_irrelevant: "bg-pdm-canvas text-pdm-muted",
};

export function MessageRow({ message }: { message: InboxMessage }) {
  const username = message.follower.username ? `@${message.follower.username}` : "Unknown sender";
  const status = inboundStatusLabel(message.status);
  const badgeStyle = (message.category && CATEGORY_STYLES[message.category]) ?? "bg-pdm-card text-pdm-ink ring-1 ring-pdm-border";

  return (
    <LiveItem>
      <Link
        href={`/inbox/${message.follower.id}`}
        className={cardLinkClass()}
      >
        <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
          <p className="font-semibold">{username}</p>
          <LocalTime value={message.receivedAt} className="text-xs text-pdm-muted" />
        </div>

        <p className="line-clamp-2 text-sm text-pdm-ink">{message.text || "(No text — attachment only)"}</p>

        <div className="flex flex-wrap items-center gap-2 text-xs">
          <span className={`rounded-full px-2 py-0.5 font-semibold ${badgeStyle}`}>{categoryLabel(message.category)}</span>
          {message.overridden ? <span className="text-pdm-muted">Label changed by you</span> : null}
          {message.confidence !== null && !message.overridden ? (
            <span className="text-pdm-muted">{Math.round(message.confidence * 100)}% confident</span>
          ) : null}
          {status ? <span className="text-pdm-muted">· {status}</span> : null}
        </div>
      </Link>
    </LiveItem>
  );
}
