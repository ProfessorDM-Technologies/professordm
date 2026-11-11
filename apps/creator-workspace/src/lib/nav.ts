// Workspace navigation data, shared by the desktop glass top bar and the mobile glass tab bar (spec section 4).

export type NavIconName = "bank" | "incoming" | "inbox" | "sent" | "moderation" | "knowledge" | "profile";

export const NAV_ITEMS = [
  { href: "/", label: "Bank", mobile: true, icon: "bank" },
  { href: "/incoming", label: "Incoming", mobile: true, icon: "incoming" },
  { href: "/inbox", label: "Inbox", mobile: true, icon: "inbox" },
  { href: "/sent", label: "Sent", mobile: true, icon: "sent" },
  { href: "/moderation", label: "Moderation", mobile: true, icon: "moderation" },
  { href: "/knowledge", label: "Knowledge", mobile: false, icon: "knowledge" },
  // Profile is reached from the avatar menu (UI v2 spec, requirement 6).
] as const satisfies readonly { href: string; label: string; mobile: boolean; icon: NavIconName }[];

export type NavItem = (typeof NAV_ITEMS)[number];

export function isActive(pathname: string, href: string): boolean {
  if (href === "/") {
    return pathname === "/";
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function mobileNavItems(): NavItem[] {
  return NAV_ITEMS.filter((item) => item.mobile);
}

/** Text for the Inbox count badge, or null when there is nothing to show (zero, or the count failed to load). */
export function inboxBadgeText(count: number | null | undefined): string | null {
  if (!count || count <= 0) return null;
  return count > 99 ? "99+" : String(count);
}
