"use client";

import { usePathname, useSelectedLayoutSegment } from "next/navigation";
import { ViewTransition, type ReactNode } from "react";

/**
 * Cross-fade + rise between workspace sections (UI v2 spec, motion a). Keyed by the top-level section, so moving
 * within the inbox (list → chat, chat → chat) doesn't replay the page animation, and realtime refreshes never animate.
 */
export function PageTransition({ children }: { children: ReactNode }) {
  const section = useSelectedLayoutSegment() ?? "bank";
  return (
    <ViewTransition key={section} enter="page-enter" exit="page-exit" default="none">
      <div>{children}</div>
    </ViewTransition>
  );
}

/** A lighter fade for the conversation / question pane when switching chats from the rail. The rail itself stays. */
export function PaneTransition({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  return (
    <ViewTransition key={pathname} enter="pane-enter" exit="pane-exit" default="none">
      <div className="min-w-0">{children}</div>
    </ViewTransition>
  );
}
