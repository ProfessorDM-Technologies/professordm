"use server";

import { refresh } from "next/cache";
import { parseReply } from "@/lib/inbox/reply";
import { createClient } from "@/lib/supabase/server";

export type SendReplyState =
  | { status: "idle" }
  | { status: "sent"; clientRequestId: string }
  | { status: "error"; message: string };

const SEND_FAILED = "Your reply couldn't be delivered. Check the conversation before trying again.";

// The API verifies the user token, reserves the outbound ID, and delivers to Instagram.
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
  const { data: userData, error: userError } = await supabase.auth.getUser();
  if (userError || !userData.user) {
    return { status: "error", message: SEND_FAILED };
  }
  const { data: sessionData, error: sessionError } = await supabase.auth.getSession();
  const jwt = sessionData.session?.access_token;
  const sendUrl = process.env.INSTAGRAM_SEND_API_URL;
  if (sessionError || !jwt || !sendUrl || !sendUrl.startsWith("https://")) {
    return { status: "error", message: SEND_FAILED };
  }

  let response: Response;
  try {
    response = await fetch(sendUrl, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${jwt}` },
      body: JSON.stringify({ inbound_message_id: inboundMessageId, text, client_request_id: clientRequestId }),
      cache: "no-store",
    });
  } catch {
    return { status: "error", message: SEND_FAILED };
  }
  refresh();
  if (!response.ok) {
    return { status: "error", message: SEND_FAILED };
  }
  let delivery: { status?: unknown };
  try {
    delivery = await response.json() as { status?: unknown };
  } catch {
    return { status: "error", message: SEND_FAILED };
  }
  if (!delivery || (delivery.status !== "sent" && delivery.status !== "pending")) {
    return { status: "error", message: SEND_FAILED };
  }
  return { status: "sent", clientRequestId };
}
