// Pure: merges the separate tables into one conversation. No Supabase access here so it can be unit tested.

export type ThreadInbound = { id: string; text: string | null; receivedAt: string };
export type ThreadClarification = { id: string; messageId: string; round: number; prompt: string | null; reply: string | null };
export type ThreadOutbound = { id: string; text: string | null; sentAt: string | null; type: string; status: string | null };

export type ThreadItem = {
  key: string;
  direction: "in" | "out";
  kind: "message" | "clarification_prompt" | "clarification_reply" | "outbound";
  text: string | null;
  time: string | null;
  /** Only on outbound items. */
  outboundType?: string;
  status?: string | null;
};

type Block = { sortTime: number | null; order: number; items: ThreadItem[] };

function toTime(value: string | null) {
  if (!value) return null;
  const time = Date.parse(value);
  return Number.isNaN(time) ? null : time;
}

/**
 * Inbound messages in time order, each followed by its clarification prompt(s) and the follower's reply.
 * Outbound sends sit at their sent time. Anything without a time goes last.
 * On equal times, inbound comes before outbound.
 */
export function buildThread({
  inbound,
  clarifications,
  outbound,
}: {
  inbound: ThreadInbound[];
  clarifications: ThreadClarification[];
  outbound: ThreadOutbound[];
}): ThreadItem[] {
  const roundsByMessage = new Map<string, ThreadClarification[]>();
  for (const round of clarifications) {
    const list = roundsByMessage.get(round.messageId) ?? [];
    list.push(round);
    roundsByMessage.set(round.messageId, list);
  }

  const blocks: Block[] = [];

  for (const message of inbound) {
    const items: ThreadItem[] = [
      { key: `in-${message.id}`, direction: "in", kind: "message", text: message.text, time: message.receivedAt },
    ];
    const rounds = (roundsByMessage.get(message.id) ?? []).toSorted((a, b) => a.round - b.round);
    for (const round of rounds) {
      if (round.prompt) {
        items.push({ key: `cp-${round.id}`, direction: "out", kind: "clarification_prompt", text: round.prompt, time: null });
      }
      if (round.reply) {
        items.push({ key: `cr-${round.id}`, direction: "in", kind: "clarification_reply", text: round.reply, time: null });
      }
    }
    blocks.push({ sortTime: toTime(message.receivedAt), order: 0, items });
  }

  for (const send of outbound) {
    blocks.push({
      sortTime: toTime(send.sentAt),
      order: 1,
      items: [
        {
          key: `out-${send.id}`,
          direction: "out",
          kind: "outbound",
          text: send.text,
          time: send.sentAt,
          outboundType: send.type,
          status: send.status,
        },
      ],
    });
  }

  return blocks
    .toSorted((a, b) => {
      if (a.sortTime === null && b.sortTime === null) return a.order - b.order;
      if (a.sortTime === null) return 1;
      if (b.sortTime === null) return -1;
      return a.sortTime - b.sortTime || a.order - b.order;
    })
    .flatMap((block) => block.items);
}
