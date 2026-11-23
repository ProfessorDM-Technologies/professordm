import { AccountMenuLink } from "@/components/account-menu-link";
import { signOut } from "@/lib/auth/actions";

function initials(name: string | null) {
  if (!name) return null;
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return parts.length === 0 ? null : (parts[0][0] + (parts.length > 1 ? parts.at(-1)![0] : "")).toUpperCase();
}

// Avatar button that opens a native popover (light-dismiss and Esc for free, no client JS).
export function AccountMenu({ displayName }: { displayName: string | null }) {
  const letters = initials(displayName);

  return (
    <>
      <button
        type="button"
        popoverTarget="account-menu"
        aria-label={`${letters ?? "Account"}, account menu for ${displayName ?? "you"}`}
        className="pdm-press grid size-10 place-items-center rounded-full bg-pdm-navy font-display text-sm font-bold text-white ring-2 ring-transparent hover:ring-pdm-cyan/60 dark:bg-pdm-cyan dark:text-pdm-midnight"
      >
        {letters ?? (
          <svg aria-hidden="true" viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round">
            <path d="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm-7 8a7 7 0 0 1 14 0" />
          </svg>
        )}
      </button>
      <div
        id="account-menu"
        popover="auto"
        className="pdm-popover w-64 space-y-3 rounded-2xl border border-pdm-border bg-pdm-panel p-4 text-pdm-ink shadow-pdm"
      >
        <div className="min-w-0 space-y-1.5">
          <p className="truncate font-semibold">{displayName ?? "Signed in"}</p>
          <span className="inline-block rounded-full bg-pdm-tint px-2.5 py-0.5 text-xs font-semibold text-pdm-accent-strong">
            Member
          </span>
        </div>
        <AccountMenuLink href="/profile">
          <svg aria-hidden="true" viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round">
            <path d="M12 12a4 4 0 1 0 0-8 4 4 0 0 0 0 8Zm-7 8a7 7 0 0 1 14 0" />
          </svg>
          Profile and settings
        </AccountMenuLink>
        <form action={signOut}>
          <button
            type="submit"
            className="pdm-press mt-1 min-h-11 w-full rounded-full border border-pdm-border bg-pdm-panel px-4 text-sm font-semibold text-pdm-ink hover:border-pdm-accent hover:bg-pdm-subtle"
          >
            Sign out
          </button>
        </form>
      </div>
    </>
  );
}
