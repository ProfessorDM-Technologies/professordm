import Link from "next/link";
import { entryExcerpt, entryTitle, type KnowledgeEntry } from "@/lib/knowledge/search";

export function EntryCard({ entry }: { entry: KnowledgeEntry }) {
  const title = entryTitle(entry);
  return (
    <article className="rounded-lg border border-flora-border bg-white p-4">
      <h3 className="font-semibold text-flora-ink">
        <Link href={`/entry/${entry.id}`} className="underline-offset-4 hover:underline">
          {title}
        </Link>
      </h3>
      <p className="mt-2 text-sm text-flora-muted">{entryExcerpt(entry.content)}</p>
      {entry.tags && entry.tags.length > 0 ? (
        <ul className="mt-3 flex flex-wrap gap-2" aria-label={`Topics for ${title}`}>
          {entry.tags.map((tag) => (
            <li key={tag} className="rounded-full bg-flora-tint px-3 py-1 text-xs font-medium text-flora-accent-strong">
              {tag}
            </li>
          ))}
        </ul>
      ) : null}
    </article>
  );
}
