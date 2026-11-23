/* eslint-disable @next/next/no-img-element -- static SVG/WebP brand assets; next/image adds nothing here */
import type { Metadata } from "next";
import type { ReactNode } from "react";

export const metadata: Metadata = {
  title: { template: "%s | ProfessorDM", default: "ProfessorDM" },
  robots: { index: false, follow: false },
};

// Visitors arrive here from an Instagram link without an account, so the logo is not a link into the app.
export default function ProfessorDMLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="px-3 pt-[max(0.75rem,env(safe-area-inset-top))] sm:px-4 xl:px-6 xl:pt-4">
        <div role="img" aria-label="ProfessorDM" className="inline-flex items-center gap-2.5 p-1">
          <img src="/brand/mark.webp" alt="" width={278} height={192} className="h-9 w-auto xl:h-12" />
          <img src="/brand/wordmark-light.svg" alt="" width={530} height={96} className="h-[1.125rem] w-auto dark:hidden xl:h-6" />
          <img src="/brand/wordmark-dark.svg" alt="" width={530} height={96} className="hidden h-[1.125rem] w-auto dark:block xl:h-6" />
        </div>
      </header>
      <main className="mx-auto w-full max-w-xl flex-1 px-4 pt-8 pb-16 sm:px-6">{children}</main>
    </div>
  );
}
