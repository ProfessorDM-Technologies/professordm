"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

// A link inside the account popover. Client navigation keeps the layout mounted, so close the popover by hand.
export function AccountMenuLink({ href, children }: { href: string; children: ReactNode }) {
  const pathname = usePathname();
  const active = pathname === href || pathname.startsWith(`${href}/`);

  return (
    <Link
      href={href}
      aria-current={active ? "page" : undefined}
      onClick={(event) => event.currentTarget.closest<HTMLElement>("[popover]")?.hidePopover()}
      className={`pdm-press flex min-h-11 items-center gap-3 rounded-xl px-3 text-sm font-semibold ${
        active ? "bg-pdm-tint text-pdm-accent-strong" : "text-pdm-ink hover:bg-pdm-subtle"
      }`}
    >
      {children}
    </Link>
  );
}
