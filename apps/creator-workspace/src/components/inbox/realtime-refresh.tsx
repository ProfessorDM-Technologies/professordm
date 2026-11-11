"use client";

import { startTransition, useEffect } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";

// Re-read server-rendered rows when RLS-visible message, question or draft changes arrive. The refresh runs as a
// transition, so the current screen stays put and new rows rise in (LiveList) instead of the page flashing.
export function RealtimeRefresh() {
  const router = useRouter();

  useEffect(() => {
    const supabase = createClient();
    const channel = supabase
      .channel("creator-workspace-messages")
      .on("postgres_changes", { event: "*", schema: "public", table: "inbound_messages" }, () => startTransition(() => router.refresh()))
      .on("postgres_changes", { event: "*", schema: "public", table: "outbound_messages" }, () => startTransition(() => router.refresh()))
      .on("postgres_changes", { event: "*", schema: "public", table: "questions" }, () => startTransition(() => router.refresh()))
      .on("postgres_changes", { event: "*", schema: "public", table: "drafts" }, () => startTransition(() => router.refresh()))
      .subscribe();
    return () => { void supabase.removeChannel(channel); };
  }, [router]);

  return null;
}
