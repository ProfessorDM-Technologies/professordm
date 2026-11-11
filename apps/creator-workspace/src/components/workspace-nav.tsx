"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { NavIcon } from "@/components/nav-icons";
import { NAV_ITEMS, inboxBadgeText, isActive, mobileNavItems, type NavItem } from "@/lib/nav";

function InboxBadge({ count, className = "" }: { count: number | null | undefined; className?: string }) {
  const text = inboxBadgeText(count);
  if (!text) return null;
  return (
    <span
      aria-label={`${count} unanswered`}
      className={`inline-flex min-w-5 items-center justify-center rounded-full bg-pdm-primary px-1.5 text-xs font-semibold leading-5 text-white ${className}`}
    >
      {text}
    </span>
  );
}

// Desktop: pills inside the glass top bar; the active pill is solid white, lifted out of the glass (spec section 4.1).
function TopItem({ item, active, inboxCount }: { item: NavItem; active: boolean; inboxCount?: number | null }) {
  return (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      className={`flex min-h-10 items-center gap-1.5 whitespace-nowrap rounded-full px-3 font-display text-sm font-semibold motion-safe:transition-colors ${
        active
          ? "bg-white text-pdm-primary shadow-sm ring-1 ring-pdm-primary/10"
          : "text-pdm-muted hover:bg-white/60 hover:text-pdm-primary"
      }`}
    >
      {item.label}
      {item.href === "/inbox" ? <InboxBadge count={inboxCount} /> : null}
    </Link>
  );
}

// Mobile: icon over label, with a navy indicator above the active item (spec section 4.2).
function BottomItem({ item, active, inboxCount }: { item: NavItem; active: boolean; inboxCount?: number | null }) {
  return (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      className={`relative flex min-h-14 flex-col items-center justify-center gap-0.5 px-1 text-xs font-medium motion-safe:transition-colors ${
        active
          ? "text-pdm-primary before:absolute before:inset-x-4 before:top-0 before:h-[3px] before:rounded-b-full before:bg-pdm-primary"
          : "text-pdm-muted hover:text-pdm-primary"
      }`}
    >
      <span className="relative">
        <NavIcon name={item.icon} />
        {item.href === "/inbox" ? <InboxBadge count={inboxCount} className="absolute -top-1.5 left-3.5" /> : null}
      </span>
      {item.label}
    </Link>
  );
}

export function WorkspaceNav({
  variant,
  className,
  inboxCount,
}: {
  variant: "top" | "bottom";
  className?: string;
  inboxCount?: number | null;
}) {
  const pathname = usePathname();
  const items = variant === "bottom" ? mobileNavItems() : NAV_ITEMS;
  const Item = variant === "bottom" ? BottomItem : TopItem;

  return (
    <nav aria-label="Main" className={className}>
      <ul className={variant === "top" ? "flex items-center gap-0.5" : "flex"}>
        {items.map((item) => (
          <li key={item.href} className={variant === "bottom" ? "flex-1" : undefined}>
            <Item item={item} active={isActive(pathname, item.href)} inboxCount={inboxCount} />
          </li>
        ))}
      </ul>
    </nav>
  );
}
