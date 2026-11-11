import type { ReactNode } from "react";

export function Placeholder({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-xl border border-dashed border-pdm-border bg-white/60 p-4 text-sm text-pdm-muted">
      {children}
    </div>
  );
}
