export const FREE_ANSWER_LIMIT = 5;

export function freeAnswersLeft(used: number | null | undefined) {
  const safeUsed = typeof used === "number" && Number.isFinite(used) ? Math.max(0, Math.floor(used)) : 0;
  return Math.max(0, FREE_ANSWER_LIMIT - safeUsed);
}
