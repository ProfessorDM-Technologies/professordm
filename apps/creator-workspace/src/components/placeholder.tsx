import type { ReactNode } from "react";

export function Placeholder({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-pdm-border bg-white p-4 text-sm text-pdm-muted">
      {children}
    </div>
  );
}
