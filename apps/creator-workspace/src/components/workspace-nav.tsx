"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

// Simple line icons (brand guide §05: clean line icons over clip-art). Used by the mobile dock.
const ICONS: Record<string, ReactNode> = {
  "/": <path d="M3 10h18M5 10v8m4.7-8v8m4.6-8v8M19 10v8M3 20h18M12 3l9 5H3l9-5Z" />,
  "/incoming": <path d="M4 13h4l1.5 3h5L16 13h4M5 6h14l1 7v6H4v-6l1-7Z" />,
  "/inbox": <path d="M4 5h16v11H9l-5 4V5Zm7.2 3.7a1.8 1.8 0 1 1 2.5 1.7c-.5.3-.9.7-.9 1.3m.1 2.1h.01" />,
  "/moderation": <path d="M12 3 5 6v5c0 4.4 3 8.3 7 10 4-1.7 7-5.6 7-10V6l-7-3Zm-3 9 2 2 4-4" />,
  "/knowledge": <path d="M4 5.5C6.5 4 9.5 4 12 5.5V20c-2.5-1.5-5.5-1.5-8 0V5.5Zm16 0C17.5 4 14.5 4 12 5.5V20c2.5-1.5 5.5-1.5 8 0V5.5Z" />,
};

// Profile lives in the account menu (top right), not here.
const NAV_ITEMS = [
  { href: "/", label: "Bank", dock: true },
  { href: "/incoming", label: "Incoming", dock: true },
  { href: "/inbox", label: "Inbox", dock: true },
  { href: "/sent", label: "Sent", dock: false },
  { href: "/moderation", label: "Moderation", dock: true },
  { href: "/knowledge", label: "Knowledge", dock: true },
] as const;

function matches(pathname: string, href: string) {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

// The dock has no Sent tab, so Sent lights up Inbox (they share the queue tabs).
function isActive(pathname: string, href: string, variant: "island" | "dock") {
  if (variant === "dock" && href === "/inbox" && matches(pathname, "/sent")) return true;
  return matches(pathname, href);
}

// "island": the floating glass pill at the top (xl and up). "dock": the same pill docked at the bottom below xl.
export function WorkspaceNav({ variant, className = "" }: { variant: "island" | "dock"; className?: string }) {
  const pathname = usePathname();
  const items = variant === "dock" ? NAV_ITEMS.filter((item) => item.dock) : NAV_ITEMS;

  return (
    <nav aria-label="Main" className={`pdm-glass rounded-full p-1 ${className}`}>
      <ul className="flex items-center">
        {items.map((item) => {
          const active = isActive(pathname, item.href, variant);
          return (
            <li key={item.href} className={variant === "dock" ? "flex-1" : undefined}>
              <Link
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={
                  variant === "island"
                    ? `pdm-press relative flex min-h-9 items-center rounded-full px-3 font-display text-[0.8125rem] font-semibold ${
                        active
                          ? "bg-(--pdm-glass-active) text-pdm-heading shadow-[0_1px_3px_rgb(4_59_101/0.12),inset_0_1px_0_rgb(255_255_255/0.6)]"
                          : "text-pdm-muted hover:bg-(--pdm-glass-active) hover:text-pdm-ink"
                      }`
                    : `pdm-press flex min-h-13 flex-col items-center justify-center gap-0.5 rounded-full px-1 text-[0.6875rem] font-semibold ${
                        active
                          ? "bg-(--pdm-glass-active) text-pdm-heading shadow-[inset_0_1px_0_rgb(255_255_255/0.5)]"
                          : "text-pdm-muted"
                      }`
                }
              >
                {variant === "island" ? (
                  // Absolutely placed so the labels never shift when the active item changes.
                  <span
                    aria-hidden="true"
                    className={`absolute bottom-1 left-1/2 size-1 -translate-x-1/2 rounded-full bg-pdm-teal transition-opacity duration-200 ease-pdm ${
                      active ? "opacity-100" : "opacity-0"
                    }`}
                  />
                ) : (
                  <svg
                    aria-hidden="true"
                    viewBox="0 0 24 24"
                    className={`size-5 ${active ? "text-pdm-teal" : ""}`}
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="1.7"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    {ICONS[item.href]}
                  </svg>
                )}
                {item.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
