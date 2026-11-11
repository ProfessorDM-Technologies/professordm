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

// The solid pill behind the active item. Its view-transition-name lets it glide to the next item on navigation
// (UI v2 spec, motion a) while the labels stay crisp.
function ActivePill({ name }: { name: string }) {
  return (
    <span
      aria-hidden="true"
      style={{ viewTransitionName: name }}
      className="absolute inset-0 -z-10 rounded-full bg-pdm-card shadow-sm ring-1 ring-pdm-primary/10"
    />
  );
}

// Desktop: pills inside the glass island; the active pill is solid, lifted out of the glass.
function TopItem({ item, active, inboxCount }: { item: NavItem; active: boolean; inboxCount?: number | null }) {
  return (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      className={`relative isolate flex min-h-9 items-center gap-1.5 whitespace-nowrap rounded-full px-3 font-display text-sm font-semibold motion-safe:transition-[color,background-color,scale] motion-safe:active:scale-95 ${
        active ? "text-pdm-primary" : "text-pdm-muted hover:bg-pdm-card/50 hover:text-pdm-primary"
      }`}
    >
      {active ? <ActivePill name="nav-pill" /> : null}
      {/* Named so the label paints above the gliding pill during the transition. */}
      <span style={{ viewTransitionName: `nav-label-${item.icon}` }} className="flex items-center gap-1.5">
        {item.label}
        {item.href === "/inbox" ? <InboxBadge count={inboxCount} /> : null}
      </span>
    </Link>
  );
}

// Mobile floating island: icon over label; the active item sits on a solid pill lifted out of the glass (UI v2 spec).
function BottomItem({ item, active, inboxCount }: { item: NavItem; active: boolean; inboxCount?: number | null }) {
  return (
    <Link
      href={item.href}
      aria-current={active ? "page" : undefined}
      className={`relative isolate flex min-h-13 flex-col items-center justify-center gap-0.5 rounded-full px-1 text-[0.6875rem] font-semibold motion-safe:transition-[color,background-color,scale] motion-safe:active:scale-95 ${
        active ? "text-pdm-primary" : "text-pdm-muted hover:text-pdm-primary"
      }`}
    >
      {active ? <ActivePill name="nav-pill-mobile" /> : null}
      <span style={{ viewTransitionName: `nav-mlabel-${item.icon}` }} className="flex flex-col items-center gap-0.5">
        <span className="relative">
          <NavIcon name={item.icon} />
          {item.href === "/inbox" ? <InboxBadge count={inboxCount} className="absolute -top-1.5 left-3.5" /> : null}
        </span>
        {item.label}
      </span>
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
