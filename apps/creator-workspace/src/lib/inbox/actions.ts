"use server";

import { revalidatePath } from "next/cache";
import { parseReply } from "@/lib/inbox/reply";
import { createClient } from "@/lib/supabase/server";

export type SendReplyState =
  | { status: "idle" }
  | { status: "sent"; clientRequestId: string }
  | { status: "error"; message: string };

const SEND_FAILED = "Your reply wasn't sent. Try again.";

// Queues the creator's typed reply as a pending direct answer. The sender delivers it to Instagram.
export async function sendReply(_prev: SendReplyState, formData: FormData): Promise<SendReplyState> {
  const parsed = parseReply({
    text: formData.get("text"),
    inboundMessageId: formData.get("inbound_message_id"),
    clientRequestId: formData.get("client_request_id"),
  });
  if (!parsed.ok) {
    return { status: "error", message: parsed.error };
  }
  const { text, inboundMessageId, clientRequestId } = parsed.reply;

  const supabase = await createClient();

  // Recipient and creator come from the database, never from the form. RLS hides other creators' messages.
  const [inboundRes, creatorRes] = await Promise.all([
    supabase
      .from("inbound_messages")
      .select("id, follower_id")
      .eq("id", inboundMessageId)
      .maybeSingle<{ id: string; follower_id: string }>(),
    supabase.rpc("current_creator_id"),
  ]);

  if (inboundRes.error || creatorRes.error) {
    console.error("sendReply lookup failed", { code: (inboundRes.error ?? creatorRes.error)?.code });
    return { status: "error", message: SEND_FAILED };
  }
  if (!inboundRes.data) {
    return { status: "error", message: "This message is no longer available." };
  }
  const creatorId = creatorRes.data as string | null;
  if (!creatorId) {
    return { status: "error", message: "Only creator accounts can send replies." };
  }

  const { error } = await supabase.from("outbound_messages").insert({
    type: "answer",
    status: "pending",
    inbound_message_id: inboundRes.data.id,
    follower_id: inboundRes.data.follower_id,
    text,
    creator_id: creatorId,
    client_request_id: clientRequestId,
  });

  // 23505 = unique violation on client_request_id: this Send press was already saved (double click or retry).
  if (error && error.code !== "23505") {
    // Log the error code only. DM text never goes into logs (BASELINE.md section 3 rule 7).
    console.error("sendReply insert failed", { code: error.code });
    return { status: "error", message: SEND_FAILED };
  }

  revalidatePath(`/inbox/${inboundRes.data.follower_id}`);
  return { status: "sent", clientRequestId };
}
