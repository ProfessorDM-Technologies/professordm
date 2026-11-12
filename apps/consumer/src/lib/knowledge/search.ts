export type KnowledgeEntry = {
  id: string;
  title: string | null;
  content: string | null;
  tags: string[] | null;
};

function toWords(text: string) {
  return text
    .toLowerCase()
    .replace(/['’]/g, "")
    .split(/[^\p{L}\p{N}]+/u)
    .filter(Boolean);
}

export function searchTerms(query: string) {
  return toWords(query);
}

export function filterEntries<T extends KnowledgeEntry>(entries: T[], query: string) {
  if (!query.trim()) {
    return entries;
  }
  const terms = searchTerms(query);
  if (terms.length === 0) {
    return [];
  }
  return entries.filter((entry) => {
    const words = toWords([entry.title ?? "", entry.content ?? "", ...(entry.tags ?? [])].join(" "));
    return terms.every((term) => words.some((word) => word.startsWith(term)));
  });
}

export function popularTopics(entries: Pick<KnowledgeEntry, "tags">[], limit = 8) {
  const counts = new Map<string, number>();
  for (const entry of entries) {
    for (const tag of new Set((entry.tags ?? []).map((t) => t.trim().toLowerCase()).filter(Boolean))) {
      counts.set(tag, (counts.get(tag) ?? 0) + 1);
    }
  }
  return [...counts.entries()]
    .sort(([a, countA], [b, countB]) => countB - countA || a.localeCompare(b))
    .slice(0, limit)
    .map(([tag]) => tag);
}

export function entryTitle(entry: KnowledgeEntry) {
  const title = entry.title?.trim();
  if (title) {
    return title;
  }
  const firstLine = entry.content?.trim().split("\n")[0] ?? "";
  return firstLine.length > 80 ? `${firstLine.slice(0, 77)}…` : firstLine || "Untitled answer";
}

export function entryExcerpt(content: string | null, maxLength = 160) {
  const text = (content ?? "").replace(/\s+/g, " ").trim();
  return text.length > maxLength ? `${text.slice(0, maxLength - 1).trimEnd()}…` : text;
}
