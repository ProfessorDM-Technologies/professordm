import Link from "next/link";
import { redirect } from "next/navigation";
import type { ReactNode } from "react";
import { CreatorNav } from "@/components/creator-nav";
import { LOGIN_PATH } from "@/lib/routes";
import { createClient } from "@/lib/supabase/server";

export default async function SignedInLayout({ children }: { children: ReactNode }) {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    redirect(LOGIN_PATH);
  }

  return (
    <div className="flex min-h-dvh flex-col">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-50 focus:rounded-lg focus:bg-white focus:px-4 focus:py-2 focus:font-medium focus:shadow"
      >
        Skip to content
      </a>
      <header className="border-b border-flora-border bg-white">
        <div className="mx-auto flex w-full max-w-3xl items-center justify-between px-4 py-3">
          <Link href="/" className="text-lg font-semibold tracking-tight text-flora-accent-strong">
            Ask Sweetlife Flora
          </Link>
          <CreatorNav className="hidden md:block" />
        </div>
      </header>
      <main id="main" tabIndex={-1} className="mx-auto w-full max-w-3xl flex-1 px-4 pb-24 pt-6 md:pb-10">
        {children}
      </main>
      <CreatorNav className="fixed inset-x-0 bottom-0 border-t border-flora-border bg-white pb-[env(safe-area-inset-bottom)] md:hidden" />
    </div>
  );
}
