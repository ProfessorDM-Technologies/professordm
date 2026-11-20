"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

// Simple line icons (brand guide §05: clean line icons over clip-art). Used by the mobile dock.
const ICONS: Record<string, ReactNode> = {
  "/": <path d="M3 10h18M5 10v8m4.7-8v8m4.6-8v8M19 10v8M3 20h18M12 3l9 5H3l9-5Z" />,
  "/incoming": <path d="M4 13h4l1.5 3h5L16 13h4M5 6h14l1 7v6H4v-6l1-7Z" />,
  "/inbox": <path d="M4 5h16v11H9l-5 4V5Zm7.2 3.7a1.8 1.8 0 1 1 2.5 1.7c-.5.3-.9.7-.9 1.3m.1 2.1h.01" />,
  "/sent": <path d="m4 12 16-8-6 16-2.5-6.5L4 12Zm7.5 1.5L20 4" />,
  "/moderation": <path d="M12 3 5 6v5c0 4.4 3 8.3 7 10 4-1.7 7-5.6 7-10V6l-7-3Zm-3 9 2 2 4-4" />,
  "/knowledge": <path d="M4 5.5C6.5 4 9.5 4 12 5.5V20c-2.5-1.5-5.5-1.5-8 0V5.5Zm16 0C17.5 4 14.5 4 12 5.5V20c2.5-1.5 5.5-1.5 8 0V5.5Z" />,
  "/profile": <path d="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm-7 8a7 7 0 0 1 14 0" />,
};

const NAV_ITEMS = [
  { href: "/", label: "Bank", mobile: true },
  { href: "/incoming", label: "Incoming", mobile: true },
  { href: "/inbox", label: "Inbox", mobile: true },
  { href: "/sent", label: "Sent", mobile: false },
  { href: "/moderation", label: "Moderation", mobile: true },
  { href: "/knowledge", label: "Knowledge", mobile: false },
  { href: "/profile", label: "Profile", mobile: true },
] as const;

function isActive(pathname: string, href: string) {
  if (href === "/") {
    return pathname === "/";
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

// "island": the floating glass pill at the top (xl and up). "dock": the same pill docked at the bottom on phones.
export function WorkspaceNav({ variant, className = "" }: { variant: "island" | "dock"; className?: string }) {
  const pathname = usePathname();
  const items = variant === "dock" ? NAV_ITEMS.filter((item) => item.mobile) : NAV_ITEMS;

  return (
    <nav aria-label="Main" className={`pdm-glass rounded-full p-1.5 ${className}`}>
      <ul className="flex items-center gap-0.5">
        {items.map((item) => {
          const active = isActive(pathname, item.href);
          return (
            <li key={item.href} className={variant === "dock" ? "flex-1" : undefined}>
              <Link
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={
                  variant === "island"
                    ? `pdm-press relative flex min-h-10 items-center gap-2 rounded-full px-3.5 font-display text-sm font-semibold ${
                        active
                          ? "bg-pdm-panel text-pdm-heading shadow-[0_1px_2px_rgb(18_35_46/0.08)]"
                          : "text-pdm-muted hover:bg-pdm-subtle hover:text-pdm-ink"
                      }`
                    : `pdm-press flex min-h-14 flex-col items-center justify-center gap-0.5 rounded-full px-1 text-[0.6875rem] font-semibold ${
                        active ? "bg-pdm-panel text-pdm-heading" : "text-pdm-muted"
                      }`
                }
              >
                {variant === "island" ? (
                  <span
                    aria-hidden="true"
                    className={`size-1.5 rounded-full bg-pdm-teal transition-[scale,opacity] duration-200 ease-pdm ${
                      active ? "scale-100 opacity-100" : "-ml-2 scale-0 opacity-0"
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
