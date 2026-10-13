import { createHmac, timingSafeEqual } from "node:crypto";

export function verifyMetaSignature(rawBody: Buffer, signature: string | undefined, appSecret: string): boolean {
  if (!signature || !/^sha256=[a-f0-9]{64}$/i.test(signature)) return false;
  const expected = createHmac("sha256", appSecret).update(rawBody).digest();
  const received = Buffer.from(signature.slice(7), "hex");
  return received.length === expected.length && timingSafeEqual(received, expected);
}

export interface InboundEvent {
  recipientIgUserId: string;
  senderScopedId: string;
  mid: string;
  text: string | null;
  receivedAt: string | null;
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function nonemptyString(value: unknown): string | null {
  return typeof value === "string" && value.length > 0 ? value : null;
}

/** Isolated until a real Meta test event confirms the exact payload fields. */
export function parseInboundEvents(body: unknown): InboundEvent[] {
  const root = record(body);
  if (root?.object !== "instagram" || !Array.isArray(root.entry)) return [];

  const events: InboundEvent[] = [];
  for (const entryValue of root.entry) {
    const entry = record(entryValue);
    if (!Array.isArray(entry?.messaging)) continue;
    for (const itemValue of entry.messaging) {
      const item = record(itemValue);
      const message = record(item?.message);
      if (!item || !message || message.is_echo === true) continue;
      const recipientIgUserId = nonemptyString(record(item.recipient)?.id);
      const senderScopedId = nonemptyString(record(item.sender)?.id);
      const mid = nonemptyString(message.mid);
      if (!recipientIgUserId || !senderScopedId || !mid) continue;

      const timestamp = item.timestamp;
      const milliseconds = typeof timestamp === "number" ? timestamp :
        typeof timestamp === "string" && /^\d+$/.test(timestamp) ? Number(timestamp) : NaN;
      const receivedAt = Number.isFinite(milliseconds) && milliseconds >= 0 && milliseconds <= 8.64e15
        ? new Date(milliseconds).toISOString()
        : null;
      events.push({
        recipientIgUserId,
        senderScopedId,
        mid,
        text: typeof message.text === "string" ? message.text : null,
        receivedAt,
      });
    }
  }
  return events;
}
