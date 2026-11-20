import type { ReactNode } from "react";

export function Placeholder({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-2xl border border-dashed border-pdm-border bg-pdm-panel/60 p-5 text-sm text-pdm-muted">
      {children}
    </div>
  );
}
