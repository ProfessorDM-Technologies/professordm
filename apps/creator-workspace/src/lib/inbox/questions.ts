import "server-only";
import { notFound } from "next/navigation";
import type { QuestionStatus } from "@professordm/contracts";
import { createClient } from "@/lib/supabase/server";

// Reads for the question queues (docs/plans/creator-inbox-spec.md section 5).
// RLS limits every row to the signed-in creator (admins see all). Log error codes only:
// question, draft and answer text, tags and citations never go into logs.

export const INBOX_STATUSES = ["paid", "drafting", "awaiting_creator", "approved", "delivering"] as const satisfies readonly QuestionStatus[];
export const SENT_STATUSES = ["delivered", "accepted", "closed"] as const satisfies readonly QuestionStatus[];

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

type Supabase = Awaited<ReturnType<typeof createClient>>;
type Follower = { id: string; username: string | null };

export type QueueDraft = {
  id: string;
  status: string | null;
  coverage: string | null;
  reason: string | null;
  aiText: string | null;
  finalText: string | null;
  sourceCount: number;
};

export type LastSend = { status: string | null; createdAt: string };

export type QueueQuestion = {
  id: string;
  status: string;
  questionText: string;
  source: string;
  paidAt: string | null;
  deliveredAt: string | null;
  priceCents: number | null;
  follower: Follower | null;
  /** The answer draft (not a follow-up draft). Null when the AI couldn't draft. */
  draft: QueueDraft | null;
  lastSend: LastSend | null;
  openFlagIds: string[];
  tags: string[];
};

/**
 * `flagsError`: the questions loaded but their open flags didn't, so flagged cards can't be marked.
 * `loadedAt`: when the rows were read (ms), the reference point for wait times.
 */
export type QueueResult = { questions: QueueQuestion[]; error: boolean; flagsError: boolean; loadedAt: number };

type OutboundRow = { status: string | null; created_at: string };

type DraftRow = {
  id: string;
  followup_id: string | null;
  status: string | null;
  knowledge_coverage: string | null;
  reason: string | null;
  ai_text: string | null;
  final_text: string | null;
  citations: unknown;
  outbound_messages: OutboundRow[];
};

type QuestionRow = {
  id: string;
  status: string;
  question_text: string;
  source: string;
  paid_at: string | null;
  delivered_at: string | null;
  price_cents: number | null;
  origin_message_id: string | null;
  follower: Follower | null;
  drafts: DraftRow[];
  question_tags: { tags: { name: string } | null }[];
};

type FlagRow = {
  id: string;
  target_type: string;
  target_id: string;
  checkpoint: string | null;
  layer: string | null;
  category: string | null;
  detail: string | null;
  status: string;
};

const QUEUE_SELECT =
  "id, status, question_text, source, paid_at, delivered_at, price_cents, origin_message_id, " +
  "follower:ig_followers(id, username), " +
  "drafts(id, followup_id, status, knowledge_coverage, reason, ai_text, final_text, citations, outbound_messages(status, created_at)), " +
  "question_tags(tags(name))";

function answerDraft<T extends { followup_id: string | null }>(drafts: T[]): T | null {
  return drafts.find((draft) => draft.followup_id === null) ?? null;
}

function newestSend(sends: OutboundRow[]): LastSend | null {
  const newest = sends.toSorted((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))[0];
  return newest ? { status: newest.status, createdAt: newest.created_at } : null;
}

function countCitations(citations: unknown): number {
  return Array.isArray(citations) ? citations.length : 0;
}

// A flag belongs to a question when it is on its origin message or on its answer draft.
function flagIdsFor(flags: FlagRow[], originMessageId: string | null, draftId: string | null): string[] {
  return flags
    .filter(
      (flag) =>
        (flag.target_type === "message" && flag.target_id === originMessageId) ||
        (flag.target_type === "draft" && flag.target_id === draftId),
    )
    .map((flag) => flag.id);
}

async function fetchOpenFlags(supabase: Supabase): Promise<{ flags: FlagRow[]; error: boolean }> {
  const { data, error } = await supabase
    .from("safety_flags")
    .select("id, target_type, target_id, checkpoint, layer, category, detail, status")
    .eq("status", "open")
    .in("target_type", ["message", "draft"])
    .overrideTypes<FlagRow[], { merge: false }>();
  if (error) {
    console.error("fetchOpenFlags failed", { code: error.code });
    return { flags: [], error: true };
  }
  return { flags: data ?? [], error: false };
}

function toQueueQuestion(row: QuestionRow, openFlags: FlagRow[]): QueueQuestion {
  const draft = answerDraft(row.drafts ?? []);
  return {
    id: row.id,
    status: row.status,
    questionText: row.question_text,
    source: row.source,
    paidAt: row.paid_at,
    deliveredAt: row.delivered_at,
    priceCents: row.price_cents,
    follower: row.follower,
    draft: draft
      ? {
          id: draft.id,
          status: draft.status,
          coverage: draft.knowledge_coverage,
          reason: draft.reason,
          aiText: draft.ai_text,
          finalText: draft.final_text,
          sourceCount: countCitations(draft.citations),
        }
      : null,
    lastSend: draft ? newestSend(draft.outbound_messages ?? []) : null,
    openFlagIds: flagIdsFor(openFlags, row.origin_message_id, draft?.id ?? null),
    tags: (row.question_tags ?? []).flatMap((link) => (link.tags ? [link.tags.name] : [])),
  };
}

/**
 * "inbox": questions waiting for the creator, oldest paid_at first (whoever waited longest is on top),
 * questions with open flags first. "sent": delivered answers, newest first.
 */
export async function listQuestions(queue: "inbox" | "sent"): Promise<QueueResult> {
  const supabase = await createClient();
  const inbox = queue === "inbox";
  const query = supabase
    .from("questions")
    .select(QUEUE_SELECT)
    .in("status", inbox ? [...INBOX_STATUSES] : [...SENT_STATUSES])
    .order(inbox ? "paid_at" : "delivered_at", { ascending: inbox, nullsFirst: false })
    .limit(100)
    .overrideTypes<QuestionRow[], { merge: false }>();

  const [{ data, error }, flagsRes] = await Promise.all([
    query,
    inbox ? fetchOpenFlags(supabase) : Promise.resolve({ flags: [] as FlagRow[], error: false }),
  ]);

  if (error) {
    console.error("listQuestions failed", { queue, code: error.code });
    return { questions: [], error: true, flagsError: false, loadedAt: Date.now() };
  }

  const questions = (data ?? []).map((row) => toQueueQuestion(row, flagsRes.flags));
  return {
    // toSorted is stable, so the paid_at order holds inside each group.
    questions: inbox
      ? questions.toSorted((a, b) => Number(b.openFlagIds.length > 0) - Number(a.openFlagIds.length > 0))
      : questions,
    error: false,
    flagsError: flagsRes.error,
    loadedAt: Date.now(),
  };
}

export type QuestionFlag = {
  id: string;
  targetType: "message" | "draft";
  checkpoint: string | null;
  layer: string | null;
  category: string | null;
  detail: string | null;
  status: string;
};

export type QuestionDetail = {
  id: string;
  status: string;
  questionText: string;
  safetyFlagged: boolean;
  paidAt: string | null;
  priceCents: number | null;
  source: string;
  originMessageId: string | null;
  follower: Follower | null;
  draft: {
    id: string;
    status: string | null;
    aiText: string | null;
    citations: Citation[];
    coverage: string | null;
    missingInfo: string[];
    reason: string | null;
    finalText: string | null;
    approvedAt: string | null;
  } | null;
  origin: {
    text: string | null;
    receivedAt: string;
    category: string | null;
    confidence: number | null;
    reason: string | null;
  } | null;
  clarifications: { id: string; round: number; prompt: string | null; reply: string | null }[];
  flags: QuestionFlag[];
  lastSend: LastSend | null;
};

export type Citation = { kind: string | null; ref: string | null; title: string | null; supports: string | null };

export type QuestionResult = { question: QuestionDetail; error: boolean };

type DetailRow = Omit<QuestionRow, "drafts" | "question_tags"> & {
  safety_flagged: boolean;
  drafts: (Omit<DraftRow, "outbound_messages"> & { missing_info: unknown; approved_at: string | null })[];
};

type OriginRow = {
  text: string | null;
  received_at: string;
  category: string | null;
  override_category: string | null;
  confidence: number | string | null;
  reason: string | null;
};

function toCitations(value: unknown): Citation[] {
  if (!Array.isArray(value)) return [];
  const text = (field: unknown) => (typeof field === "string" && field.trim() ? field : null);
  return value.flatMap((item) =>
    item && typeof item === "object"
      ? [{ kind: text(item.kind), ref: text(item.ref), title: text(item.title), supports: text(item.supports) }]
      : [],
  );
}

function toStringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string" && item.trim() !== "") : [];
}

// One question with everything the answer workspace shows. Missing or another creator's: 404.
export async function getQuestion(id: string): Promise<QuestionResult> {
  if (!UUID_PATTERN.test(id)) {
    notFound();
  }

  const supabase = await createClient();
  const { data: row, error } = await supabase
    .from("questions")
    .select(
      "id, status, question_text, safety_flagged, paid_at, delivered_at, price_cents, source, origin_message_id, " +
        "follower:ig_followers(id, username), " +
        "drafts(id, followup_id, status, ai_text, citations, knowledge_coverage, missing_info, reason, final_text, approved_at)",
    )
    .eq("id", id)
    .maybeSingle()
    .overrideTypes<DetailRow, { merge: false }>();

  if (error) {
    console.error("getQuestion failed", { code: error.code });
    throw new Error("getQuestion failed");
  }
  if (!row) {
    notFound();
  }

  const draft = answerDraft(row.drafts ?? []);
  const originId = row.origin_message_id;

  const flagTargets = [
    originId ? `and(target_type.eq.message,target_id.eq.${originId})` : null,
    draft ? `and(target_type.eq.draft,target_id.eq.${draft.id})` : null,
  ].filter(Boolean);

  const [originRes, roundsRes, flagsRes, sendRes] = await Promise.all([
    originId
      ? supabase
          .from("inbound_messages")
          .select("text, received_at, category, override_category, confidence, reason")
          .eq("id", originId)
          .maybeSingle()
          .overrideTypes<OriginRow, { merge: false }>()
      : Promise.resolve({ data: null, error: null }),
    originId
      ? supabase
          .from("clarification_rounds")
          .select("id, round, prompt, reply")
          .eq("message_id", originId)
          .order("round", { ascending: true })
          .overrideTypes<QuestionDetail["clarifications"], { merge: false }>()
      : Promise.resolve({ data: [], error: null }),
    flagTargets.length
      ? supabase
          .from("safety_flags")
          .select("id, target_type, target_id, checkpoint, layer, category, detail, status")
          .in("status", ["open", "creator_reviewed"])
          .or(flagTargets.join(","))
          .overrideTypes<FlagRow[], { merge: false }>()
      : Promise.resolve({ data: [], error: null }),
    draft
      ? supabase
          .from("outbound_messages")
          .select("status, created_at")
          .eq("draft_id", draft.id)
          .order("created_at", { ascending: false })
          .limit(1)
          .overrideTypes<OutboundRow[], { merge: false }>()
      : Promise.resolve({ data: [], error: null }),
  ]);

  const failed = [originRes.error, roundsRes.error, flagsRes.error, sendRes.error].find(Boolean);
  if (failed) {
    console.error("getQuestion details failed", { code: failed.code });
  }

  const origin = originRes.data;
  return {
    error: Boolean(failed),
    question: {
      id: row.id,
      status: row.status,
      questionText: row.question_text,
      safetyFlagged: row.safety_flagged,
      paidAt: row.paid_at,
      priceCents: row.price_cents,
      source: row.source,
      originMessageId: originId,
      follower: row.follower,
      draft: draft
        ? {
            id: draft.id,
            status: draft.status,
            aiText: draft.ai_text,
            citations: toCitations(draft.citations),
            coverage: draft.knowledge_coverage,
            missingInfo: toStringList(draft.missing_info),
            reason: draft.reason,
            finalText: draft.final_text,
            approvedAt: draft.approved_at,
          }
        : null,
      origin: origin
        ? {
            text: origin.text,
            receivedAt: origin.received_at,
            category: origin.override_category ?? origin.category,
            confidence: origin.confidence === null ? null : Number(origin.confidence),
            reason: origin.reason,
          }
        : null,
      clarifications: roundsRes.data ?? [],
      flags: (flagsRes.data ?? []).map((flag) => ({
        id: flag.id,
        targetType: flag.target_type === "draft" ? "draft" : "message",
        checkpoint: flag.checkpoint,
        layer: flag.layer,
        category: flag.category,
        detail: flag.detail,
        status: flag.status,
      })),
      lastSend: newestSend(sendRes.data ?? []),
    },
  };
}

export type QueueCounts = { inbox: number | null; sent: number | null; moderation: number | null };

// Tab counts. A count that fails to load is null, and the tab shows no number.
export async function queueCounts(): Promise<QueueCounts> {
  const supabase = await createClient();
  const [inbox, sent, flags, decisions] = await Promise.all([
    supabase.from("questions").select("id", { count: "exact", head: true }).in("status", [...INBOX_STATUSES]),
    supabase.from("questions").select("id", { count: "exact", head: true }).in("status", [...SENT_STATUSES]),
    supabase
      .from("safety_flags")
      .select("id", { count: "exact", head: true })
      .eq("status", "open")
      .in("target_type", ["message", "draft"]),
    supabase.from("inbound_messages").select("id", { count: "exact", head: true }).eq("status", "creator_decision"),
  ]);

  for (const [name, res] of Object.entries({ inbox, sent, flags, decisions })) {
    if (res.error) console.error("queueCounts failed", { count: name, code: res.error.code });
  }

  return {
    inbox: inbox.error ? null : (inbox.count ?? 0),
    sent: sent.error ? null : (sent.count ?? 0),
    moderation: flags.error || decisions.error ? null : (flags.count ?? 0) + (decisions.count ?? 0),
  };
}

export type FlaggedQuestion = {
  id: string;
  status: string;
  questionText: string;
  follower: Follower | null;
  flags: QuestionFlag[];
};

export type FlaggedResult = { questions: FlaggedQuestion[]; error: boolean };

// Open flags grouped by the question they belong to (via its origin message or its answer draft).
// A flag on a message that never became a question has no row here.
export async function listOpenFlags(): Promise<FlaggedResult> {
  const supabase = await createClient();
  const { flags, error } = await fetchOpenFlags(supabase);
  if (error) return { questions: [], error: true };
  if (flags.length === 0) return { questions: [], error: false };

  const messageIds = flags.filter((flag) => flag.target_type === "message").map((flag) => flag.target_id);
  const draftIds = flags.filter((flag) => flag.target_type === "draft").map((flag) => flag.target_id);

  const draftsRes = draftIds.length
    ? await supabase
        .from("drafts")
        .select("id, question_id")
        .in("id", draftIds)
        .overrideTypes<{ id: string; question_id: string }[], { merge: false }>()
    : { data: [], error: null };
  const questionByDraft = new Map((draftsRes.data ?? []).map((draft) => [draft.id, draft.question_id]));

  const filters = [
    messageIds.length ? `origin_message_id.in.(${messageIds.join(",")})` : null,
    questionByDraft.size ? `id.in.(${[...new Set(questionByDraft.values())].join(",")})` : null,
  ].filter(Boolean);

  const questionsRes = filters.length
    ? await supabase
        .from("questions")
        .select("id, status, question_text, origin_message_id, paid_at, follower:ig_followers(id, username)")
        .or(filters.join(","))
        .order("paid_at", { ascending: true, nullsFirst: false })
        .overrideTypes<
          { id: string; status: string; question_text: string; origin_message_id: string | null; follower: Follower | null }[],
          { merge: false }
        >()
    : { data: [], error: null };

  const failed = draftsRes.error ?? questionsRes.error;
  if (failed) {
    console.error("listOpenFlags failed", { code: failed.code });
    return { questions: [], error: true };
  }

  return {
    error: false,
    questions: (questionsRes.data ?? []).flatMap((question) => {
      const own = flags.filter((flag) =>
        flag.target_type === "message"
          ? flag.target_id === question.origin_message_id
          : questionByDraft.get(flag.target_id) === question.id,
      );
      return own.length
        ? [
            {
              id: question.id,
              status: question.status,
              questionText: question.question_text,
              follower: question.follower,
              flags: own.map((flag) => ({
                id: flag.id,
                targetType: flag.target_type === "draft" ? ("draft" as const) : ("message" as const),
                checkpoint: flag.checkpoint,
                layer: flag.layer,
                category: flag.category,
                detail: flag.detail,
                status: flag.status,
              })),
            },
          ]
        : [];
    }),
  };
}

export type DecisionMessage = {
  id: string;
  text: string | null;
  receivedAt: string;
  category: string | null;
  reason: string | null;
  follower: Follower;
};

export type DecisionResult = { messages: DecisionMessage[]; error: boolean };

// DMs the AI handed to the creator to decide on (for example a safety concern), newest first.
export async function listDecisionMessages(): Promise<DecisionResult> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("inbound_messages")
    .select("id, text, received_at, category, override_category, reason, follower:ig_followers!inner(id, username)")
    .eq("status", "creator_decision")
    .order("received_at", { ascending: false })
    .limit(50)
    .overrideTypes<(Omit<OriginRow, "confidence"> & { id: string; follower: Follower | null })[], { merge: false }>();

  if (error) {
    console.error("listDecisionMessages failed", { code: error.code });
    return { messages: [], error: true };
  }

  return {
    error: false,
    messages: (data ?? []).flatMap((row) =>
      row.follower
        ? [
            {
              id: row.id,
              text: row.text,
              receivedAt: row.received_at,
              category: row.override_category ?? row.category,
              reason: row.reason,
              follower: row.follower,
            },
          ]
        : [],
    ),
  };
}
