// Pure: publishing answer entries on the Knowledge page (docs/plans/scrum-143-publish-answers-spec.md).
// The database function set_knowledge_entry_published (migration 014) does the write.

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export type PublishInput = { entryId: string; published: boolean };

export const PUBLISH_MESSAGES = {
  session: "Your session expired. Sign in again.",
  unavailable: "This entry is unavailable for your account. Refresh the page.",
  invalid: "This change couldn't be saved. Refresh the page and try again.",
  unknown: "Couldn't save. Try again.",
} as const;

/** Form fields from the Publish / Make private button: entry_id and published ("true" or "false"). */
export function parsePublish(fields: { entryId: unknown; published: unknown }): { ok: true; input: PublishInput } | { ok: false } {
  const { entryId, published } = fields;
  if (typeof entryId !== "string" || !UUID_PATTERN.test(entryId) || (published !== "true" && published !== "false")) {
    return { ok: false };
  }
  return { ok: true, input: { entryId: entryId.toLowerCase(), published: published === "true" } };
}

// Error codes raised by migration 014: 28000 not signed in, P0002 not found, 22023 missing value.
export function publishErrorMessage(error: { code?: string }): string {
  if (error.code === "28000") return PUBLISH_MESSAGES.session;
  if (error.code === "P0002") return PUBLISH_MESSAGES.unavailable;
  if (error.code === "22023") return PUBLISH_MESSAGES.invalid;
  return PUBLISH_MESSAGES.unknown;
}

export function entryTitle(entry: { title: string | null; content: string | null }): string {
  const title = entry.title?.trim();
  if (title) return title;
  const firstLine = entry.content
    ?.split("\n")
    .map((line) => line.trim())
    .find(Boolean);
  return firstLine || "Untitled answer";
}

/** Newest delivered question first; entries without a delivered question after, by title. */
export function sortAnswerEntries<E extends { title: string | null; content: string | null; deliveredAt: string | null }>(
  entries: readonly E[],
): E[] {
  return entries.toSorted((a, b) => {
    if (a.deliveredAt && b.deliveredAt) return Date.parse(b.deliveredAt) - Date.parse(a.deliveredAt);
    if (a.deliveredAt) return -1;
    if (b.deliveredAt) return 1;
    return entryTitle(a).localeCompare(entryTitle(b));
  });
}
