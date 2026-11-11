import Link from "next/link";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";
import { AccountMenu } from "@/components/account-menu";
import { BrandMark } from "@/components/brand/brand-mark";
import { BrandMist } from "@/components/brand/brand-mist";
import { WorkspaceNav } from "@/components/workspace-nav";
import { getSessionUser, isWorkspaceRole } from "@/lib/auth/session";
import { queueCounts } from "@/lib/inbox/questions";
import { LOGIN_PATH } from "@/lib/routes";

export default async function WorkspaceLayout({ children }: { children: ReactNode }) {
  const session = await getSessionUser();

  if (!session) {
    redirect(LOGIN_PATH);
  }

  if (!isWorkspaceRole(session.role)) {
    redirect("/auth/forbidden");
  }

  // Unanswered count for the Inbox badge. A failed count is null and shows no badge.
  const { inbox: inboxCount } = await queueCounts();

  return (
    <div className="min-h-dvh">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[60] focus:rounded-lg focus:bg-pdm-card focus:px-4 focus:py-2 focus:font-medium focus:shadow"
      >
        Skip to content
      </a>

      <BrandMist />

      <header className="glass sticky top-0 z-40 border-b">
        <div className="mx-auto flex h-16 w-full max-w-6xl items-center gap-4 px-4 md:px-8">
          <Link
            href="/"
            aria-label="ProfessorDM Creator Workspace home"
            className="flex shrink-0 items-center gap-2.5 rounded-lg"
          >
            <BrandMark />
            <span className="hidden font-display text-sm font-semibold text-pdm-heading lg:inline">Creator Workspace</span>
          </Link>
          <WorkspaceNav variant="top" inboxCount={inboxCount} className="hidden min-w-0 flex-1 md:block" />
          <div className="ml-auto shrink-0">
            <AccountMenu displayName={session.displayName} role={session.role} />
          </div>
        </div>
      </header>

      <main id="main" tabIndex={-1} className="mx-auto w-full max-w-6xl px-4 pb-28 pt-8 md:px-8 md:pb-12">
        {children}
      </main>

      <WorkspaceNav
        variant="bottom"
        inboxCount={inboxCount}
        className="glass fixed inset-x-0 bottom-0 z-40 border-t pb-[env(safe-area-inset-bottom)] md:hidden"
      />
    </div>
  );
}
