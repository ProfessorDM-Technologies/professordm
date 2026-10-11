"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

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

export function WorkspaceNav({ variant, className }: { variant: "sidebar" | "bottom"; className?: string }) {
  const pathname = usePathname();
  const items = variant === "bottom" ? NAV_ITEMS.filter((item) => item.mobile) : NAV_ITEMS;

  return (
    <nav aria-label="Main" className={className}>
      <ul className={variant === "sidebar" ? "space-y-1" : "flex"}>
        {items.map((item) => {
          const active = isActive(pathname, item.href);
          return (
            <li key={item.href} className={variant === "bottom" ? "flex-1" : undefined}>
              <Link
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={
                  variant === "sidebar"
                    ? `flex min-h-11 items-center rounded-lg px-3 text-sm font-medium ${
                        active ? "bg-pdm-tint text-pdm-accent-strong" : "text-pdm-muted hover:bg-pdm-surface hover:text-pdm-ink"
                      }`
                    : `flex min-h-12 items-center justify-center px-1 text-xs font-medium ${
                        active ? "text-pdm-accent" : "text-pdm-muted hover:text-pdm-ink"
                      }`
                }
              >
                {item.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
