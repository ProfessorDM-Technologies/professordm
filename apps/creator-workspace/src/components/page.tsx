import type { ReactNode } from "react";

// Readable widths (UI v2 spec, requirement 5): list pages read in a ~70ch column; split views get room for two panes.
export type PageWidth = "narrow" | "wide" | "full";

const WIDTHS: Record<PageWidth, string> = {
  narrow: "max-w-3xl",
  wide: "max-w-6xl",
  // The inbox detail views: rail + conversation or rail + two-column answer workspace.
  full: "max-w-7xl",
};

export function pageWidthClass(width: PageWidth): string {
  return `mx-auto w-full ${WIDTHS[width]}`;
}

export function Page({
  width = "narrow",
  className = "",
  children,
  ...rest
}: { width?: PageWidth; className?: string; children: ReactNode; "aria-busy"?: boolean }) {
  return (
    <div className={`${pageWidthClass(width)} ${className}`} {...rest}>
      {children}
    </div>
  );
}
