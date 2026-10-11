import Link from "next/link";

const TABS = [
  { href: "/inbox", label: "Inbox" },
  { href: "/sent", label: "Sent" },
  { href: "/moderation", label: "Moderation" },
] as const;

type QueueHref = (typeof TABS)[number]["href"];

// Inbox | Sent | Moderation strip shared by the three queue pages (diagram 05, Flow 2). Counts come later.
export function QueueTabs({ current }: { current: QueueHref }) {
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
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
