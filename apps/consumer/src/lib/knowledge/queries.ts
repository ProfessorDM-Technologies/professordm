import { cache } from "react";
import { createClient } from "@/lib/supabase/server";
import type { KnowledgeEntry } from "./search";

const ENTRY_COLUMNS = "id, title, content, tags";
const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export async function getPublishedEntries() {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("knowledge_entries")
    .select(ENTRY_COLUMNS)
    .eq("published", true)
    .order("title", { ascending: true })
    .limit(200)
    .overrideTypes<KnowledgeEntry[], { merge: false }>();
  if (error) {
    throw new Error("Could not load answers");
  }
  return data ?? [];
}

export async function getPublishedTags() {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("knowledge_entries")
    .select("tags")
    .eq("published", true)
    .limit(500)
    .overrideTypes<Pick<KnowledgeEntry, "tags">[], { merge: false }>();
  if (error) {
    throw new Error("Could not load topics");
  }
  return data ?? [];
}

export const getPublishedEntry = cache(async (id: string) => {
  if (!UUID_PATTERN.test(id)) {
    return null;
  }
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("knowledge_entries")
    .select(ENTRY_COLUMNS)
    .eq("id", id)
    .eq("published", true)
    .maybeSingle()
    .overrideTypes<KnowledgeEntry, { merge: false }>();
  if (error) {
    throw new Error("Could not load this answer");
  }
  return data;
});

export async function getFreeViewsUsed(profileId: string) {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("consumers")
    .select("free_views_used")
    .eq("profile_id", profileId)
    .order("id", { ascending: true })
    .limit(1)
    .overrideTypes<{ free_views_used: number }[], { merge: false }>();
  if (error) {
    throw new Error("Could not load your free answers");
  }
  return data?.[0]?.free_views_used ?? 0;
}

export async function getDisplayName(profileId: string) {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("profiles")
    .select("display_name")
    .eq("id", profileId)
    .maybeSingle()
    .overrideTypes<{ display_name: string | null }, { merge: false }>();
  if (error) {
    throw new Error("Could not load your profile");
  }
  return data?.display_name ?? null;
}
