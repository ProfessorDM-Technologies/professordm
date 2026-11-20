import Link from "next/link";
import type { ReactNode } from "react";

// Line icons drawn from the logo's story (question → knowledge → value) plus a few workspace symbols.
const ICONS = {
  question: <path d="M5 5h14v10h-7l-5 4v-4H5V5Zm5.2 3.3a1.9 1.9 0 1 1 2.6 1.8c-.5.2-.8.6-.8 1.1M12 13.2h.01" />,
  money: <path d="M5 5h14v10h-7l-5 4v-4H5V5Zm9 2.6c-.4-.6-1.1-.9-2-.9-1.2 0-2 .6-2 1.4 0 1.9 4 1 4 2.9 0 .8-.8 1.4-2 1.4-.9 0-1.7-.4-2.1-1M12 5.8v1M12 12.4v1" />,
  book: <path d="M4 5.5C6.5 4 9.5 4 12 5.5V20c-2.5-1.5-5.5-1.5-8 0V5.5Zm16 0C17.5 4 14.5 4 12 5.5V20c2.5-1.5 5.5-1.5 8 0V5.5Z" />,
  shield: <path d="M12 3 5 6v5c0 4.4 3 8.3 7 10 4-1.7 7-5.6 7-10V6l-7-3Zm-3 9 2 2 4-4" />,
  inbox: <path d="M4 13h4l1.5 3h5L16 13h4M5 6h14l1 7v6H4v-6l1-7Z" />,
  send: <path d="m4 12 16-8-6 16-2.5-6.5L4 12Zm7.5 1.5L20 4" />,
  list: <path d="M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01" />,
  settings: <path d="M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm7.4-3a7.4 7.4 0 0 0-.1-1.2l2-1.6-2-3.4-2.4.9a7.5 7.5 0 0 0-2-1.2L14.5 3h-4l-.4 2.5a7.5 7.5 0 0 0-2 1.2l-2.4-.9-2 3.4 2 1.6a7.4 7.4 0 0 0 0 2.4l-2 1.6 2 3.4 2.4-.9a7.5 7.5 0 0 0 2 1.2l.4 2.5h4l.4-2.5a7.5 7.5 0 0 0 2-1.2l2.4.9 2-3.4-2-1.6c.1-.4.1-.8.1-1.2Z" />,
} as const;

// Cyan for questions and messages, gold for money, teal for knowledge and done work (DESIGN.md palette roles).
const TONES = {
  cyan: "bg-pdm-cyan-tint text-pdm-cyan-ink",
  gold: "bg-pdm-gold-tint text-pdm-gold-ink",
  teal: "bg-pdm-tint text-pdm-accent-strong",
} as const;

export type EmptyStateIcon = keyof typeof ICONS;

// A designed empty state: a speech-bubble icon, what this space is for, and the one thing to do next.
export function EmptyState({
  icon,
  tone = "cyan",
  title,
  children,
  action,
}: {
  icon: EmptyStateIcon;
  tone?: keyof typeof TONES;
  title: string;
  children?: ReactNode;
  action?: { href: string; label: string };
}) {
  return (
    <div className="flex items-start gap-4 rounded-2xl border border-pdm-border bg-pdm-panel p-5">
      <span aria-hidden="true" className={`grid size-12 shrink-0 place-items-center rounded-2xl rounded-bl-md ${TONES[tone]}`}>
        <svg viewBox="0 0 24 24" className="size-6" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
          {ICONS[icon]}
        </svg>
      </span>
      <div className="min-w-0 space-y-1 pt-0.5">
        <p className="font-display font-bold text-pdm-heading">{title}</p>
        {children ? <div className="text-sm text-pdm-muted">{children}</div> : null}
        {action ? (
          <Link
            href={action.href}
            className="pdm-press mt-2 inline-flex min-h-11 items-center rounded-full border border-pdm-border px-4 text-sm font-semibold text-pdm-ink hover:border-pdm-accent hover:bg-pdm-subtle"
          >
            {action.label}
          </Link>
        ) : null}
      </div>
    </div>
  );
}
