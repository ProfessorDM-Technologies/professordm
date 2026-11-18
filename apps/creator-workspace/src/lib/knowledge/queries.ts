import "server-only";
import { sortAnswerEntries } from "@/lib/knowledge/answer-entries";
import { createClient } from "@/lib/supabase/server";

// Reads for the Knowledge page (SCRUM-143). RLS (migration 008) limits rows to the signed-in creator's entries
// (admins see all). Log error codes only: answer text never goes into logs.

export type AnswerEntry = {
  id: string;
  title: string | null;
  content: string | null;
  tags: string[];
  published: boolean;
  questionId: string | null;
  /** When the answer was delivered, from its question. Null for entries without one (test rows). */
  deliveredAt: string | null;
};

type EntryRow = {
  id: string;
  title: string | null;
  content: string | null;
  tags: string[] | null;
  published: boolean;
  question_id: string | null;
  question: { delivered_at: string | null } | null;
};

export type AnswerEntriesResult = { entries: AnswerEntry[]; error: boolean };

// Saved answers (source = 'question'), newest delivered first. Guide chunks and manual facts are not listed here.
export async function listAnswerEntries(): Promise<AnswerEntriesResult> {
  const supabase = await createClient();
  const { data, error } = await supabase
    .from("knowledge_entries")
    .select("id, title, content, tags, published, question_id, question:questions(delivered_at)")
    .eq("source", "question")
    .limit(200)
    .overrideTypes<EntryRow[], { merge: false }>();

  if (error) {
    console.error("listAnswerEntries failed", { code: error.code });
    return { entries: [], error: true };
  }

  return {
    error: false,
    entries: sortAnswerEntries(
      (data ?? []).map((row) => ({
        id: row.id,
        title: row.title,
        content: row.content,
        tags: row.tags ?? [],
        published: row.published,
        questionId: row.question_id,
        deliveredAt: row.question?.delivered_at ?? null,
      })),
    ),
  };
}
