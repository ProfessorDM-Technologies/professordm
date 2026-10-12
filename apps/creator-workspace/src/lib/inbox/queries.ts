import "server-only";
import { createClient } from "@/lib/supabase/server";

export type InboxMessage = {
  id: string;
  text: string | null;
  /** override_category when the creator corrected the AI, otherwise the AI category. */
  category: string | null;
  overridden: boolean;
  confidence: number | null;
  status: string | null;
  receivedAt: string;
  follower: { id: string; username: string | null };
};

type InboundRow = {
  id: string;
  text: string | null;
  category: string | null;
  override_category: string | null;
  confidence: number | string | null;
  status: string | null;
  received_at: string;
  follower: { id: string; username: string | null } | null;
};

export type InboxResult = { messages: InboxMessage[]; error: boolean };

// RLS limits rows to the signed-in creator's contacts (admins see all). Newest first.
export async function listInboundMessages({ limit = 50 }: { limit?: number } = {}): Promise<InboxResult> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("inbound_messages")
    .select(
      "id, text, category, override_category, confidence, status, received_at, follower:ig_followers!inner(id, username)",
    )
    .order("received_at", { ascending: false })
    .limit(limit)
    .overrideTypes<InboundRow[], { merge: false }>();

  if (error) {
    // Log the error code only. DM text never goes into logs (BASELINE.md section 3 rule 7).
    console.error("listInboundMessages failed", { code: error.code });
    return { messages: [], error: true };
  }

  return {
    messages: (data ?? []).flatMap((row) =>
      row.follower
        ? [
            {
              id: row.id,
              text: row.text,
              category: row.override_category ?? row.category,
              overridden: row.override_category !== null && row.override_category !== row.category,
              confidence: row.confidence === null ? null : Number(row.confidence),
              status: row.status,
              receivedAt: row.received_at,
              follower: row.follower,
            },
          ]
        : [],
    ),
    error: false,
  };
}
