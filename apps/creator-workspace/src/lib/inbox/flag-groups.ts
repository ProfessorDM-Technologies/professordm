import type { QuestionFlag } from "./questions";

export type FlagRow = {
  id: string;
  target_type: string;
  target_id: string;
  checkpoint: string | null;
  layer: string | null;
  category: string | null;
  detail: string | null;
  status: string;
};

/**
 * Groups open flags under the question they belong to: a message flag via the question's origin message,
 * a draft flag via `questionByDraft` (draft id → question id). Keeps the order of `questions` and drops
 * questions without flags, so a flag on a DM that never became a question is not in the result.
 */
export function groupFlagsByQuestion<Q extends { id: string; origin_message_id: string | null }>(
  flags: readonly FlagRow[],
  questions: readonly Q[],
  questionByDraft: ReadonlyMap<string, string>,
): { question: Q; flags: QuestionFlag[] }[] {
  return questions.flatMap((question) => {
    const own = flags.filter((flag) =>
      flag.target_type === "message"
        ? flag.target_id === question.origin_message_id
        : questionByDraft.get(flag.target_id) === question.id,
    );
    if (own.length === 0) return [];
    return [
      {
        question,
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
    ];
  });
}
