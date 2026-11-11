"use client";

import { createContext, useContext, useLayoutEffect, useOptimistic, useRef, type ReactNode } from "react";
import { LiveItem } from "@/components/ui/live-list";

// How close to the bottom counts as "reading the latest" (px). Further up means the creator is reading history.
const STICK_THRESHOLD = 96;

type PendingReply = { pending: string | null; showPending: (text: string | null) => void };

const PendingReplyContext = createContext<PendingReply | null>(null);

/**
 * Shares the optimistic reply between the docked ReplyBox and the MessagePane above it (UI v2 spec, motion b).
 * useOptimistic: the "Sending…" bubble shows while the send action runs and disappears by itself when it ends,
 * by which point the refreshed thread contains the real message.
 */
export function ConversationProvider({ children }: { children: ReactNode }) {
  const [pending, showPending] = useOptimistic<string | null, string | null>(null, (_current, next) => next);
  return <PendingReplyContext.Provider value={{ pending, showPending }}>{children}</PendingReplyContext.Provider>;
}

export function usePendingReply() {
  return useContext(PendingReplyContext);
}

/**
 * The conversation's own scroll area (UI v2 spec, requirement 4). Only messages scroll here; the header above and the
 * reply box below stay put. Opens at the newest message and follows new ones unless the creator has scrolled up.
 */
export function MessagePane({ count, children }: { count: number; children: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null);
  const stickRef = useRef(true);
  const firstRef = useRef(true);
  const pending = usePendingReply()?.pending ?? null;
  const total = count + (pending ? 1 : 0);

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || !stickRef.current) return;
    const instant = firstRef.current || window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    el.scrollTo({ top: el.scrollHeight, behavior: instant ? "auto" : "smooth" });
    firstRef.current = false;
  }, [total]);

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
      className="relative min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-5 focus-visible:outline-offset-[-2px] [scrollbar-width:thin]"
    >
      {children}
      {pending ? (
        <LiveItem as="div" className="mt-4 flex justify-end motion-safe:animate-rise-in">
          <div className="flex max-w-[85%] flex-col items-end space-y-1 sm:max-w-[70%]">
            <p className="sr-only">You are sending:</p>
            <div className="whitespace-pre-wrap rounded-xl bg-pdm-human px-4 py-2 text-left text-sm text-pdm-ink opacity-80 ring-1 ring-pdm-success/20">
              {pending}
            </div>
            <p className="flex items-center gap-1.5 text-xs text-pdm-muted">
              <span aria-hidden="true" className="size-1.5 rounded-full bg-pdm-success motion-safe:animate-pulse" />
              Sending…
            </p>
          </div>
        </LiveItem>
      ) : null}
    </div>
  );
}
