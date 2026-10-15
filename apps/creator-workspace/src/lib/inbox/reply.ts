// Pure: validates the reply form. No Supabase access here so it can be unit tested.

// Keep the existing character limit and enforce Meta's UTF-8 byte limit too.
export const MAX_REPLY_LENGTH = 999;
export const MAX_REPLY_BYTES = 1000;

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export type ReplyInput = { text: string; inboundMessageId: string; clientRequestId: string };

export type ParsedReply = { ok: true; reply: ReplyInput } | { ok: false; error: string };

export function parseReply(fields: { text: unknown; inboundMessageId: unknown; clientRequestId: unknown }): ParsedReply {
  const text = typeof fields.text === "string" ? fields.text.trim() : "";
  if (!text) {
    return { ok: false, error: "Write a reply before sending." };
  }
  if (text.length > MAX_REPLY_LENGTH || new TextEncoder().encode(text).length > MAX_REPLY_BYTES) {
    return { ok: false, error: "Your reply is too long. Shorten it before sending." };
  }

  const { inboundMessageId, clientRequestId } = fields;
  if (
    typeof inboundMessageId !== "string" ||
    typeof clientRequestId !== "string" ||
    !UUID_PATTERN.test(inboundMessageId) ||
    !UUID_PATTERN.test(clientRequestId)
  ) {
    return { ok: false, error: "This reply couldn't be sent. Refresh the page and try again." };
  }

  return { ok: true, reply: { text, inboundMessageId, clientRequestId } };
}
