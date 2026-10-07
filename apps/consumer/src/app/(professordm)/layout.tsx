import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: { template: "%s | ProfessorDM", default: "ProfessorDM" },
  robots: { index: false, follow: false },
};

export default function ProfessorDMLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col bg-pdm-surface text-pdm-ink">
      <header className="border-b border-pdm-border bg-white">
        <div className="mx-auto flex w-full max-w-xl items-center px-4 py-4">
          <p className="text-lg font-semibold tracking-tight">ProfessorDM</p>
        </div>
      </header>
      <main className="mx-auto w-full max-w-xl flex-1 px-4 py-8">{children}</main>
    </div>
  );
}
