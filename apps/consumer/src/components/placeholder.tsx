import type { ReactNode } from "react";

// A slot for content that isn't built yet. Empty lists use EmptyState instead.
export function Placeholder({ children }: { children: ReactNode }) {
  return (
    <div className="rounded-2xl border border-dashed border-pdm-border bg-pdm-panel p-4 text-sm text-pdm-muted">
      {children}
    </div>
  );
}
