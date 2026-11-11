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

      {/*
        Logo stands apart in the top-left corner; the glass island (UI v2 spec, requirement 2) stays centred and holds
        only navigation and the avatar. On phones the island shrinks to the avatar alone at the top right.
      */}
      <header className="pointer-events-none sticky top-3 z-40 flex items-center justify-between px-3 md:justify-center md:px-5">
        <Link
          href="/"
          aria-label="ProfessorDM Creator Workspace home"
          className="pointer-events-auto flex shrink-0 items-center gap-2.5 rounded-xl md:absolute md:left-5"
        >
          <span className="rounded-lg shadow-[var(--glass-shadow)]">
            <BrandMark />
          </span>
          <span className="hidden font-display text-sm font-semibold text-pdm-heading xl:inline">Creator Workspace</span>
        </Link>
        <div className="glass pointer-events-auto flex items-center gap-1 rounded-full p-1.5">
          <WorkspaceNav variant="top" inboxCount={inboxCount} className="hidden md:block" />
          <AccountMenu displayName={session.displayName} role={session.role} />
        </div>
      </header>

      <main id="main" tabIndex={-1} className="mx-auto w-full max-w-6xl px-4 pt-8 pb-32 md:px-8 md:pb-16">
        {children}
      </main>

      <WorkspaceNav
        variant="bottom"
        inboxCount={inboxCount}
        className="glass fixed inset-x-3 bottom-[max(0.75rem,env(safe-area-inset-bottom))] z-40 rounded-full p-1 md:hidden"
      />
    </div>
  );
}
