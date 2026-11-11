"use client";

import { useLayoutEffect, useRef, type ReactNode } from "react";

// How close to the bottom counts as "reading the latest" (px). Further up means the creator is reading history.
const STICK_THRESHOLD = 96;

/**
 * The conversation's own scroll area (UI v2 spec, requirement 4). Only messages scroll here; the header above and the
 * reply box below stay put. Opens at the newest message and follows new ones unless the creator has scrolled up.
 */
export function MessagePane({ count, children }: { count: number; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);
  const firstRef = useRef(true);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || !stickRef.current) return;
    const instant = firstRef.current || window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    el.scrollTo({ top: el.scrollHeight, behavior: instant ? "auto" : "smooth" });
    firstRef.current = false;
  }, [count]);

  return (
    <div
      ref={ref}
      onScroll={(event) => {
        const el = event.currentTarget;
        stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < STICK_THRESHOLD;
      }}
      // Keyboard users can scroll the history with arrow keys once it has focus.
      tabIndex={0}
      aria-label="Message history"
      className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-5 focus-visible:outline-offset-[-2px] [scrollbar-width:thin]"
    >
      {children}
    </div>
  );
}
