import Link from "next/link";
import { queueCounts, type QueueCounts } from "@/lib/inbox/questions";

const TABS = [
  { href: "/inbox", label: "Inbox", count: "inbox" },
  { href: "/sent", label: "Sent", count: "sent" },
  { href: "/moderation", label: "Moderation", count: "moderation" },
] as const satisfies readonly { href: string; label: string; count: keyof QueueCounts }[];

type QueueHref = (typeof TABS)[number]["href"];

// Inbox | Sent | Moderation strip shared by the three queue pages (diagram 05, Flow 2), with counts.
// A count that failed to load is left out rather than shown as 0.
export async function QueueTabs({ current }: { current: QueueHref }) {
  const counts = await queueCounts();
  return (
    <nav aria-label="Question queues">
      <ul className="inline-flex max-w-full gap-1 overflow-x-auto rounded-full border border-pdm-border bg-pdm-panel p-1">
        {TABS.map((tab) => {
          const active = tab.href === current;
          return (
            <li key={tab.href}>
              <Link
                href={tab.href}
                aria-current={active ? "page" : undefined}
                className={`pdm-press flex min-h-10 items-center rounded-full px-4 font-display text-sm font-semibold whitespace-nowrap ${
                  active ? "bg-pdm-accent text-pdm-on-accent" : "text-pdm-muted hover:bg-pdm-subtle hover:text-pdm-ink"
                }`}
              >
                {tab.label}
                {counts[tab.count] !== null ? (
                  <span
                    className={`ml-2 rounded-full px-2 py-0.5 font-sans text-xs font-semibold tabular-nums ${
                      active ? "bg-pdm-on-accent/15 text-pdm-on-accent" : "bg-pdm-subtle text-pdm-muted"
                    }`}
                  >
                    {counts[tab.count]}
                  </span>
                ) : null}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
