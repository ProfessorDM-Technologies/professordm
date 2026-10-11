import type { User } from "@supabase/supabase-js";
import { cache } from "react";
import { createClient } from "@/lib/supabase/server";

export const WORKSPACE_ROLES = ["creator", "admin"] as const;
export type WorkspaceRole = (typeof WORKSPACE_ROLES)[number];

export function isWorkspaceRole(role: unknown): role is WorkspaceRole {
  return typeof role === "string" && (WORKSPACE_ROLES as readonly string[]).includes(role);
}

export type SessionUser = {
  user: User;
  role: string | null;
  displayName: string | null;
};

// Cached per request so the layout and pages share one auth + profiles lookup.
export const getSessionUser = cache(async (): Promise<SessionUser | null> => {
  const supabase = await createClient();
  const {
    data: { user },
  } = await supabase.auth.getUser();

  if (!user) {
    return null;
  }

  const { data: profile } = await supabase
    .from("profiles")
    .select("role, display_name")
    .eq("id", user.id)
    .maybeSingle();

  return {
    user,
    role: profile?.role ?? null,
    displayName: profile?.display_name ?? user.email ?? null,
  };
});
