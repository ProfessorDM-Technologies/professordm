"use server";

import { refresh } from "next/cache";
import { PUBLISH_MESSAGES, parsePublish, publishErrorMessage } from "@/lib/knowledge/answer-entries";
import { createClient } from "@/lib/supabase/server";

export type PublishState = { status: "idle" } | { status: "done" } | { status: "error"; message: string };

// Publishes or unpublishes one answer entry (SCRUM-143). set_knowledge_entry_published (migration 014) checks it is
// her answer entry, sets published and writes the audit row in one transaction. "unchanged" (double click, second
// tab) counts as done.
export async function setEntryPublished(_prev: PublishState, formData: FormData): Promise<PublishState> {
  const parsed = parsePublish({ entryId: formData.get("entry_id"), published: formData.get("published") });
  if (!parsed.ok) {
    return { status: "error", message: PUBLISH_MESSAGES.invalid };
  }

  const supabase = await createClient();
  const { error } = await supabase.rpc("set_knowledge_entry_published", {
    p_entry_id: parsed.input.entryId,
    p_published: parsed.input.published,
  });
  if (error) {
    // Error code only: answer text never goes into logs.
    console.error("setEntryPublished failed", { code: error.code });
    return { status: "error", message: publishErrorMessage(error) };
  }

  refresh();
  return { status: "done" };
}
