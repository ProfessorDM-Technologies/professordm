import { signOut } from "@/lib/auth/actions";
import type { WorkspaceRole } from "@/lib/auth/session";

const ROLE_LABELS: Record<WorkspaceRole, string> = {
  creator: "Creator",
  admin: "ProfessorDM admin",
};

export function AccountMenu({
  displayName,
  role,
  compact = false,
}: {
  displayName: string | null;
  role: WorkspaceRole;
  compact?: boolean;
}) {
  return (
    <div className={compact ? "flex items-center gap-3" : "space-y-3"}>
      <div className="min-w-0">
        {compact ? null : <p className="truncate text-sm font-medium">{displayName ?? "Signed in"}</p>}
        <span className="inline-block rounded-full bg-pdm-tint px-2 py-0.5 text-xs font-semibold text-pdm-accent-strong">
          {ROLE_LABELS[role]}
        </span>
      </div>
      <form action={signOut}>
        <button
          type="submit"
          className={`min-h-11 rounded-lg border border-pdm-border bg-white px-3 text-sm font-medium text-pdm-ink hover:bg-pdm-surface ${
            compact ? "" : "w-full"
          }`}
        >
          Sign out
        </button>
      </form>
    </div>
  );
}
