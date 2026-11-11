"use client";

import Link from "next/link";
import { useEffect, useRef, type KeyboardEvent } from "react";
import { buttonClass } from "@/components/ui/button-styles";
import { signOut } from "@/lib/auth/actions";
import type { WorkspaceRole } from "@/lib/auth/session";

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
        className="flex size-10 cursor-pointer list-none items-center justify-center rounded-full bg-pdm-primary-tint font-display text-sm font-bold text-pdm-primary ring-1 ring-pdm-primary/10 hover:bg-white [&::-webkit-details-marker]:hidden"
      >
        {initials(displayName)}
      </summary>
      <div className="absolute right-0 z-50 mt-2 w-64 space-y-3 rounded-xl border border-pdm-border bg-white p-4 shadow-[0_8px_24px_-12px_rgb(4_59_101/0.25)]">
        <div className="min-w-0 space-y-1">
          <p className="truncate text-sm font-semibold">{displayName ?? "Signed in"}</p>
          <span className="inline-block rounded-full bg-pdm-primary-tint px-2 py-0.5 text-xs font-semibold text-pdm-primary">
            {ROLE_LABELS[role]}
          </span>
        </div>
        <Link
          href="/knowledge"
          className="flex min-h-11 items-center rounded-lg px-3 text-sm font-medium text-pdm-ink hover:bg-pdm-canvas md:hidden"
        >
          Knowledge
        </Link>
        <form action={signOut}>
          <button type="submit" className={buttonClass("secondary", "md", "w-full")}>
            Sign out
          </button>
        </form>
      </div>
    </details>
  );
}
