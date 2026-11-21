import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";
import { AccountMenu } from "@/components/account-menu";
import { BrandLogo } from "@/components/brand-logo";
import { ThemeToggle } from "@/components/theme-toggle";
import { WorkspaceNav } from "@/components/workspace-nav";
import { getSessionUser, isWorkspaceRole } from "@/lib/auth/session";
import { LOGIN_PATH } from "@/lib/routes";
import { parseTheme, THEME_COOKIE } from "@/lib/theme";

// Fixed chrome (DESIGN.md "Layout"): logo top-left with no background, the glass nav island centred at the top
// (xl and up) or docked at the bottom (phones), and the account island top-right. None of it scrolls.
export default async function WorkspaceLayout({ children }: { children: ReactNode }) {
  const session = await getSessionUser();

  if (!session) {
    redirect(LOGIN_PATH);
  }

  if (!isWorkspaceRole(session.role)) {
    redirect("/auth/forbidden");
  }

  const theme = parseTheme((await cookies()).get(THEME_COOKIE)?.value);

  return (
    <div className="min-h-dvh">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[60] focus:rounded-full focus:bg-pdm-panel focus:px-4 focus:py-2 focus:font-semibold focus:shadow-pdm"
      >
        Skip to content
      </a>

      {/* Fades scrolled content out under the fixed row so it never collides with the logo. */}
      <div aria-hidden="true" className="pdm-scrim pointer-events-none fixed top-0 left-0 z-30 h-24 w-[80%] sm:w-[26rem] xl:h-28" />

      <header className="pointer-events-none fixed inset-x-0 top-0 z-40 grid grid-cols-[1fr_auto] items-center gap-4 px-3 pt-[max(0.75rem,env(safe-area-inset-top))] sm:px-4 xl:grid-cols-[1fr_auto_1fr] xl:px-6 xl:pt-4">
        <BrandLogo className="pointer-events-auto justify-self-start" />
        <WorkspaceNav variant="island" className="pointer-events-auto relative hidden xl:block" />
        <div className="pdm-glass pointer-events-auto relative flex items-center gap-1 justify-self-end rounded-full p-1">
          <ThemeToggle initial={theme} />
          <AccountMenu displayName={session.displayName} role={session.role} />
        </div>
      </header>

      <main
        id="main"
        tabIndex={-1}
        className="mx-auto w-full max-w-5xl px-4 pb-32 pt-24 outline-none sm:px-6 lg:px-8 xl:pb-16 xl:pt-32"
      >
        {children}
      </main>

      <WorkspaceNav
        variant="dock"
        className="fixed inset-x-3 bottom-[max(0.75rem,env(safe-area-inset-bottom))] z-40 mx-auto max-w-md xl:hidden"
      />
    </div>
  );
}
