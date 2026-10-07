import type { ReactNode } from "react";

export function Placeholder({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-flora-border bg-white p-4 text-sm text-flora-muted">
      {children}
    </div>
  );
}
