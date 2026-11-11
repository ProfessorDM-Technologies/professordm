"use client";

import { createContext, useContext, useEffect, useRef, useState, type ReactNode, type RefObject } from "react";

// Live inserts (UI v2 spec, motion d): rows that arrive after the list first appeared (a realtime refresh, a sent
// reply) rise in; rows present on first render never animate, so a chat switch or a page load stays calm and the
// server HTML always matches hydration.
const SettledContext = createContext<RefObject<boolean> | null>(null);

type ListTag = "ul" | "ol" | "div";

export function LiveList({
  as: Tag = "ul",
  className,
  children,
  ...rest
}: { as?: ListTag; className?: string; children: ReactNode; "aria-label"?: string }) {
  const settled = useRef(false);
  useEffect(() => {
    settled.current = true;
  }, []);
  return (
    <SettledContext.Provider value={settled}>
      <Tag className={className} {...rest}>
        {children}
      </Tag>
    </SettledContext.Provider>
  );
}

export function LiveItem({ as: Tag = "li", className, children }: { as?: "li" | "div"; className?: string; children: ReactNode }) {
  const settled = useContext(SettledContext);
  // Captured once at mount: true only for rows that mounted after the list had settled.
  const [fresh] = useState(() => settled?.current === true);
  const classes = [className, fresh ? "motion-safe:animate-rise-in" : null].filter(Boolean).join(" ");
  return <Tag className={classes || undefined}>{children}</Tag>;
}
