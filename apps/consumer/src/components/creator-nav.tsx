"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV_ITEMS = [
  { href: "/", label: "Home" },
  { href: "/inbox", label: "Inbox" },
  { href: "/profile", label: "Profile" },
] as const;

function isActive(pathname: string, href: string) {
  if (href === "/") {
    return pathname === "/" || pathname === "/search" || pathname.startsWith("/entry/") || pathname === "/ask-expert";
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function CreatorNav({ className }: { className?: string }) {
  const pathname = usePathname();

  return (
    <nav aria-label="Main" className={className}>
      <ul className="flex">
        {NAV_ITEMS.map((item) => {
          const active = isActive(pathname, item.href);
          return (
            <li key={item.href} className="flex-1 md:flex-none">
              <Link
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={`flex min-h-12 items-center justify-center px-4 text-sm font-medium md:rounded-lg ${
                  active ? "text-flora-accent md:bg-flora-tint" : "text-flora-muted hover:text-flora-ink"
                }`}
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
