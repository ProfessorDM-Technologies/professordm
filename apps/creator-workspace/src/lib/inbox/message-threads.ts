// Pure: groups the Incoming list into one thread per question, like email threads (SCRUM-144). No Supabase here.
//
// The only link from a follower's clarification reply to the DM it answers is the round's saved reply text:
// the AI worker stores the reply DM's text in clarification_rounds.reply on the original message. So a later
// DM from the same sender whose text equals that reply is folded under the original, the same match the
// conversation page uses (thread.ts). Every other DM is its own thread.

export type ThreadMessage = { id: string; text: string | null; receivedAt: string; follower: { id: string } };
export type ThreadRound = { messageId: string; round: number; reply: string | null };
export type MessageThread<M extends ThreadMessage> = {
  /** The DM that started the thread (the question). */
  head: M;
  /** Its clarification replies, oldest first. */
  replies: M[];
  /** Newest receivedAt in the thread; threads are sorted by this, newest first. */
  latestAt: string;
};

function toTime(value: string): number {
  const time = Date.parse(value);
  return Number.isNaN(time) ? -Infinity : time;
}

export function groupMessagesByQuestion<M extends ThreadMessage>(
  messages: readonly M[],
  rounds: readonly ThreadRound[],
): MessageThread<M>[] {
  const oldestFirst = messages.toSorted((a, b) => toTime(a.receivedAt) - toTime(b.receivedAt));
  const repliesByMessage = new Map<string, string[]>();
  for (const round of rounds.toSorted((a, b) => a.round - b.round)) {
    if (round.reply === null) continue;
    repliesByMessage.set(round.messageId, [...(repliesByMessage.get(round.messageId) ?? []), round.reply]);
  }

  const folded = new Set<string>();
  const repliesOf = new Map<string, M[]>();
  for (const head of oldestFirst) {
    const replyTexts = repliesByMessage.get(head.id);
    if (!replyTexts || folded.has(head.id)) continue;
    const found: M[] = [];
    for (const text of replyTexts) {
      const match = oldestFirst.find(
        (other) =>
          other.id !== head.id &&
          !folded.has(other.id) &&
          other.follower.id === head.follower.id &&
          other.text === text &&
          toTime(other.receivedAt) >= toTime(head.receivedAt),
      );
      if (match) {
        folded.add(match.id);
        found.push(match);
      }
    }
    repliesOf.set(head.id, found);
  }

  return oldestFirst
    .filter((message) => !folded.has(message.id))
    .map((head) => {
      const replies = repliesOf.get(head.id) ?? [];
      return { head, replies, latestAt: (replies.at(-1) ?? head).receivedAt };
    })
    .toSorted(
      (a, b) => toTime(b.latestAt) - toTime(a.latestAt) || toTime(b.head.receivedAt) - toTime(a.head.receivedAt),
    );
}
