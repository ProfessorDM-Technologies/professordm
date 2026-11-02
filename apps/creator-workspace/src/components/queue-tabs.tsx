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
      <ul className="flex gap-1 border-b border-pdm-border">
        {TABS.map((tab) => {
          const active = tab.href === current;
          return (
            <li key={tab.href}>
              <Link
                href={tab.href}
                aria-current={active ? "page" : undefined}
                className={`-mb-px flex min-h-11 items-center border-b-2 px-4 text-sm font-medium ${
                  active ? "border-pdm-accent text-pdm-accent-strong" : "border-transparent text-pdm-muted hover:text-pdm-ink"
                }`}
              >
                {tab.label}
                {counts[tab.count] !== null ? (
                  <span
                    className={`ml-2 rounded-full px-2 py-0.5 text-xs font-semibold ${
                      active ? "bg-pdm-tint text-pdm-accent-strong" : "bg-stone-100 text-pdm-muted"
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
