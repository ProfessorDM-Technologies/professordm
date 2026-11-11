"use client";

import Link from "next/link";
import { useEffect, useRef, type KeyboardEvent } from "react";
import { NavIcon } from "@/components/nav-icons";
import { ThemeSwitch } from "@/components/theme-switch";
import { buttonClass } from "@/components/ui/button-styles";
import type { NavIconName } from "@/lib/nav";
import { signOut } from "@/lib/auth/actions";
import type { WorkspaceRole } from "@/lib/auth/session";

// Profile lives here rather than in the island (UI v2 spec, requirement 6). Knowledge is in the island on desktop.
const MENU_LINKS: { href: string; label: string; icon: NavIconName; mobileOnly: boolean }[] = [
  { href: "/profile", label: "Profile", icon: "profile", mobileOnly: false },
  { href: "/knowledge", label: "Knowledge", icon: "knowledge", mobileOnly: true },
];

const ROLE_LABELS: Record<WorkspaceRole, string> = {
  creator: "Creator",
  admin: "ProfessorDM admin",
};

function initials(name: string | null) {
  const parts = (name ?? "").trim().split(/\s+/).filter(Boolean);
  if (parts.length === 0) return "PD";
  return (parts[0][0] + (parts.length > 1 ? parts[parts.length - 1][0] : "")).toUpperCase();
}

/**
 * Account disclosure in the glass top bar (a native <details>, not an ARIA menu).
 * Escape or a click outside closes it; Escape returns focus to the button.
 */
export function AccountMenu({ displayName, role }: { displayName: string | null; role: WorkspaceRole }) {
  const detailsRef = useRef<HTMLDetailsElement>(null);
  const summaryRef = useRef<HTMLElement>(null);

  useEffect(() => {
    function onPointerDown(event: PointerEvent) {
      const details = detailsRef.current;
      if (details?.open && !details.contains(event.target as Node)) details.open = false;
    }
    document.addEventListener("pointerdown", onPointerDown);
    return () => document.removeEventListener("pointerdown", onPointerDown);
  }, []);

  // The workspace layout persists across navigation, so close the menu when a link inside it is used.
  function close() {
    if (detailsRef.current) detailsRef.current.open = false;
  }

  function onKeyDown(event: KeyboardEvent<HTMLDetailsElement>) {
    if (event.key === "Escape" && detailsRef.current?.open) {
      detailsRef.current.open = false;
      summaryRef.current?.focus();
    }
  }

  return (
    <details ref={detailsRef} onKeyDown={onKeyDown} className="relative">
      <summary
        ref={summaryRef}
        aria-label="Account menu"
        className="flex size-9 cursor-pointer list-none items-center justify-center rounded-full bg-pdm-primary-tint font-display text-sm font-bold text-pdm-primary ring-1 ring-pdm-primary/15 motion-safe:transition-transform motion-safe:active:scale-95 hover:ring-pdm-primary/40 [&::-webkit-details-marker]:hidden"
      >
        {initials(displayName)}
      </summary>
      <div className="absolute right-0 z-50 mt-3 w-72 origin-top-right space-y-4 rounded-xl border border-pdm-border bg-pdm-card p-4 shadow-[0_18px_40px_-16px_rgb(4_59_101/0.45)] motion-safe:transition-[opacity,scale] motion-safe:duration-150 motion-safe:starting:scale-95 motion-safe:starting:opacity-0">
        <div className="flex items-center gap-3">
          <span className="flex size-10 shrink-0 items-center justify-center rounded-full bg-pdm-primary-tint font-display text-sm font-bold text-pdm-primary">
            {initials(displayName)}
          </span>
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold">{displayName ?? "Signed in"}</p>
            <p className="text-xs text-pdm-muted">{ROLE_LABELS[role]}</p>
          </div>
        </div>
        <nav aria-label="Account" className="-mx-1 space-y-0.5">
          {MENU_LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              onClick={close}
              className={`flex min-h-11 items-center gap-3 rounded-lg px-3 text-sm font-medium text-pdm-ink motion-safe:transition-colors hover:bg-pdm-canvas ${
                link.mobileOnly ? "md:hidden" : ""
              }`}
            >
              <NavIcon name={link.icon} className="size-[1.125rem] text-pdm-muted" />
              {link.label}
            </Link>
          ))}
        </nav>
        <ThemeSwitch />
        <form action={signOut}>
          <button type="submit" className={buttonClass("secondary", "md", "w-full")}>
            Sign out
          </button>
        </form>
      </div>
    </details>
  );
}
