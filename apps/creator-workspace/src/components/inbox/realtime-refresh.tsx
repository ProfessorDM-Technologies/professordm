"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { createClient } from "@/lib/supabase/client";

// Re-read server-rendered rows when RLS-visible message changes arrive.
export function RealtimeRefresh() {
  const router = useRouter();

  useEffect(() => {
    const supabase = createClient();
    const channel = supabase
      .channel("creator-workspace-messages")
      .on("postgres_changes", { event: "*", schema: "public", table: "inbound_messages" }, () => router.refresh())
      .on("postgres_changes", { event: "*", schema: "public", table: "outbound_messages" }, () => router.refresh())
      .subscribe();
    return () => { void supabase.removeChannel(channel); };
  }, [router]);

  return null;
}
