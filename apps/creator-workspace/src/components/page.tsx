import type { ReactNode } from "react";

// Readable widths (UI v2 spec, requirement 5): list pages read in a ~70ch column; split views get room for two panes.
export type PageWidth = "narrow" | "wide";

const WIDTHS: Record<PageWidth, string> = {
  narrow: "max-w-3xl",
  wide: "max-w-6xl",
};

export function pageWidthClass(width: PageWidth): string {
  return `mx-auto w-full ${WIDTHS[width]}`;
}

export function Page({ width = "narrow", className = "", children }: { width?: PageWidth; className?: string; children: ReactNode }) {
  return <div className={`${pageWidthClass(width)} ${className}`}>{children}</div>;
}
