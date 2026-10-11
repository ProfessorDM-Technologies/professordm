import Link from "next/link";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";
import { AccountMenu } from "@/components/account-menu";
import { WorkspaceNav } from "@/components/workspace-nav";
import { getSessionUser, isWorkspaceRole } from "@/lib/auth/session";
import { LOGIN_PATH } from "@/lib/routes";

export default async function WorkspaceLayout({ children }: { children: ReactNode }) {
  const session = await getSessionUser();

  if (!session) {
    redirect(LOGIN_PATH);
  }

  if (!isWorkspaceRole(session.role)) {
    redirect("/auth/forbidden");
  }

  const wordmark = (
    <Link href="/" className="text-lg font-semibold tracking-tight text-pdm-accent-strong">
      ProfessorDM
    </Link>
  );

  return (
    <div className="min-h-dvh">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-white focus:px-4 focus:py-2 focus:font-medium focus:shadow"
      >
        Skip to content
      </a>

      <aside className="fixed inset-y-0 left-0 hidden w-60 flex-col border-r border-pdm-border bg-white md:flex">
        <div className="px-6 py-5">
          {wordmark}
          <p className="text-xs text-pdm-muted">Creator Workspace</p>
        </div>
        <WorkspaceNav variant="sidebar" className="flex-1 overflow-y-auto px-3" />
        <div className="border-t border-pdm-border p-4">
          <AccountMenu displayName={session.displayName} role={session.role} />
        </div>
      </aside>

      <div className="flex min-h-dvh flex-col md:pl-60">
        <header className="border-b border-pdm-border bg-white md:hidden">
          <div className="flex items-center justify-between px-4 py-3">
            {wordmark}
            <AccountMenu displayName={session.displayName} role={session.role} compact />
          </div>
        </header>
        <main id="main" tabIndex={-1} className="mx-auto w-full max-w-5xl flex-1 px-4 pb-24 pt-6 md:px-8 md:pb-10">
          {children}
        </main>
      </div>

      <WorkspaceNav
        variant="bottom"
        className="fixed inset-x-0 bottom-0 border-t border-pdm-border bg-white pb-[env(safe-area-inset-bottom)] md:hidden"
      />
    </div>
  );
}
