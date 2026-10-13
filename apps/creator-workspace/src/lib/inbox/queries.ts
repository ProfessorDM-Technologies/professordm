import "server-only";
import { buildThread, type ThreadClarification, type ThreadItem, type ThreadOutbound } from "@/lib/inbox/thread";
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

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

type QuestionRow = {
  drafts: {
    final_text: string | null;
    approved_at: string | null;
    outbound_messages: { id: string; type: string; status: string | null }[];
  }[];
};

type DirectAnswerRow = { id: string; type: string; status: string | null; text: string | null; created_at: string };

export type ThreadResult =
  | { found: false }
  | {
      found: true;
      error: boolean;
      follower: { id: string; username: string | null };
      items: ThreadItem[];
      /** The newest message from this sender. A reply is linked to it. */
      latestInboundId: string | null;
    };

// One sender's conversation. RLS hides other creators' contacts, so they come back as not found.
export async function getThread(followerId: string): Promise<ThreadResult> {
  if (!UUID_PATTERN.test(followerId)) {
    return { found: false };
  }

  const supabase = await createClient();
  const { data: follower, error: followerError } = await supabase
    .from("ig_followers")
    .select("id, username")
    .eq("id", followerId)
    .maybeSingle<{ id: string; username: string | null }>();

  if (followerError) {
    console.error("getThread follower failed", { code: followerError.code });
    return { found: true, error: true, follower: { id: followerId, username: null }, items: [], latestInboundId: null };
  }
  if (!follower) {
    return { found: false };
  }

  const [inboundRes, questionsRes, directRes] = await Promise.all([
    supabase
      .from("inbound_messages")
      .select("id, text, received_at")
      .eq("follower_id", followerId)
      .order("received_at", { ascending: true })
      .overrideTypes<{ id: string; text: string | null; received_at: string }[], { merge: false }>(),
    supabase
      .from("questions")
      .select("drafts(final_text, approved_at, outbound_messages(id, type, status))")
      .eq("follower_id", followerId)
      .overrideTypes<QuestionRow[], { merge: false }>(),
    // Replies the creator typed directly (no AI draft). They carry their own text and time.
    supabase
      .from("outbound_messages")
      .select("id, type, status, text, created_at")
      .eq("follower_id", followerId)
      .is("draft_id", null)
      .overrideTypes<DirectAnswerRow[], { merge: false }>(),
  ]);

  const inbound = inboundRes.data ?? [];
  const messageIds = inbound.map((message) => message.id);

  const clarificationsRes = messageIds.length
    ? await supabase
        .from("clarification_rounds")
        .select("id, message_id, round, prompt, reply")
        .in("message_id", messageIds)
        .overrideTypes<
          { id: string; message_id: string; round: number; prompt: string | null; reply: string | null }[],
          { merge: false }
        >()
    : { data: [], error: null };

  const failed = [inboundRes.error, questionsRes.error, directRes.error, clarificationsRes.error].find(Boolean);
  if (failed) {
    console.error("getThread failed", { code: failed.code });
  }

  const clarifications: ThreadClarification[] = (clarificationsRes.data ?? []).map((row) => ({
    id: row.id,
    messageId: row.message_id,
    round: row.round,
    prompt: row.prompt,
    reply: row.reply,
  }));

  const drafted: ThreadOutbound[] = (questionsRes.data ?? []).flatMap((question) =>
    question.drafts.flatMap((draft) =>
      draft.outbound_messages.map((send) => ({
        id: send.id,
        text: draft.final_text,
        sentAt: draft.approved_at,
        type: send.type,
        status: send.status,
      })),
    ),
  );
  const direct: ThreadOutbound[] = (directRes.data ?? []).map((send) => ({
    id: send.id,
    text: send.text,
    sentAt: send.created_at,
    type: send.type,
    status: send.status,
  }));
  const outbound = [...drafted, ...direct];

  return {
    found: true,
    error: Boolean(failed),
    follower,
    latestInboundId: inbound.at(-1)?.id ?? null,
    items: buildThread({
      inbound: inbound.map((message) => ({ id: message.id, text: message.text, receivedAt: message.received_at })),
      clarifications,
      outbound,
    }),
  };
}
