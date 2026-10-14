import { createClient, type SupabaseClient } from "@supabase/supabase-js";
import { INBOUND_MESSAGE_STATUS } from "@professordm/contracts";
import type { InboundEvent } from "./meta";

export interface Persistence {
  resolveCreator(recipientIgUserId: string): Promise<string | null>;
  upsertFollower(creatorId: string, event: InboundEvent): Promise<string>;
  insertOrGetMessage(followerId: string, event: InboundEvent): Promise<string>;
}

export function createServiceRoleClient(): SupabaseClient {
  const url = process.env.SUPABASE_URL;
  const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
  if (!url || !key) throw new Error("Supabase Lambda configuration is missing");
  return createClient(url, key, { auth: { persistSession: false, autoRefreshToken: false } });
}

export function createPersistence(client: SupabaseClient): Persistence {
  return {
    async resolveCreator(recipientIgUserId) {
      const { data, error } = await client.from("ig_accounts")
        .select("creator_id").eq("ig_user_id", recipientIgUserId).maybeSingle();
      if (error) throw new Error("Instagram account lookup failed", { cause: error });
      return data?.creator_id ?? null;
    },

    async upsertFollower(creatorId, event) {
      // The schema makes ig_scoped_id globally unique, so reject any cross-creator collision.
      const { data: existing, error: lookupError } = await client.from("ig_followers")
        .select("id, creator_id, last_inbound_at").eq("ig_scoped_id", event.senderScopedId).maybeSingle();
      if (lookupError) throw new Error("Instagram follower lookup failed", { cause: lookupError });
      if (existing?.creator_id && existing.creator_id !== creatorId) {
        throw new Error("Instagram scoped ID belongs to a different creator");
      }
      const inboundAt = event.receivedAt ?? new Date().toISOString();
      const lastInboundAt = existing?.last_inbound_at && existing.last_inbound_at > inboundAt
        ? existing.last_inbound_at : inboundAt;
      const { data, error } = await client.from("ig_followers")
        .upsert({ creator_id: creatorId, ig_scoped_id: event.senderScopedId, last_inbound_at: lastInboundAt },
          { onConflict: "ig_scoped_id" })
        .select("id, creator_id").single();
      if (error || !data) throw new Error("Instagram follower upsert failed", { cause: error });
      if (data.creator_id !== creatorId) throw new Error("Instagram follower creator mismatch");
      return data.id;
    },

    async insertOrGetMessage(followerId, event) {
      const { data, error } = await client.from("inbound_messages")
        .insert({ follower_id: followerId, mid: event.mid, text: event.text,
          status: INBOUND_MESSAGE_STATUS[0], ...(event.receivedAt ? { received_at: event.receivedAt } : {}) })
        .select("id").single();
      if (data) return data.id;
      if (error?.code !== "23505") throw new Error("Inbound message insert failed", { cause: error });
      const { data: existing, error: lookupError } = await client.from("inbound_messages")
        .select("id, follower_id").eq("mid", event.mid).maybeSingle();
      if (lookupError || !existing) throw new Error("Duplicate inbound message lookup failed", { cause: lookupError });
      if (existing.follower_id !== followerId) throw new Error("Meta mid belongs to a different follower");
      return existing.id;
    },
  };
}
