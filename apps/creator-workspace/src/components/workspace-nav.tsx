"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { NavIcon } from "@/components/nav-icons";
import { NAV_ITEMS, inboxBadgeText, isActive, mobileNavItems, type NavItem } from "@/lib/nav";

function InboxBadge({ count, className = "" }: { count: number | null | undefined; className?: string }) {
  const text = inboxBadgeText(count);
  if (!text) return null;
  // aria-label is ignored on a plain span, so the visual badge is hidden and screen readers get a full phrase instead.
  return (
    <>
      <span
        aria-hidden="true"
        className={`inline-flex min-w-5 items-center justify-center rounded-full bg-pdm-primary px-1.5 text-xs font-semibold leading-5 text-pdm-on-primary ${className}`}
      >
        {text}
      </span>
      <span className="sr-only">, {count} unanswered</span>
    </>
  );
}

// Desktop: pills inside the glass island; the active pill is solid, lifted out of the glass.
function TopItem({ item, active, inboxCount }: { item: NavItem; active: boolean; inboxCount?: number | null }) {
  return (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      className={`flex min-h-9 items-center gap-1.5 whitespace-nowrap rounded-full px-3 font-display text-sm font-semibold motion-safe:transition-[color,background-color,scale] motion-safe:active:scale-95 ${
        active
          ? "bg-pdm-card text-pdm-primary shadow-sm ring-1 ring-pdm-primary/10"
          : "text-pdm-muted hover:bg-pdm-card/50 hover:text-pdm-primary"
      }`}
    >
      {item.label}
      {item.href === "/inbox" ? <InboxBadge count={inboxCount} /> : null}
    </Link>
  );
}

// Mobile floating island: icon over label; the active item sits on a solid pill lifted out of the glass (UI v2 spec).
function BottomItem({ item, active, inboxCount }: { item: NavItem; active: boolean; inboxCount?: number | null }) {
  return (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      className={`relative flex min-h-13 flex-col items-center justify-center gap-0.5 rounded-full px-1 text-[0.6875rem] font-semibold motion-safe:transition-[color,background-color,scale] motion-safe:active:scale-95 ${
        active ? "bg-pdm-card text-pdm-primary shadow-sm ring-1 ring-pdm-primary/10" : "text-pdm-muted hover:text-pdm-primary"
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
