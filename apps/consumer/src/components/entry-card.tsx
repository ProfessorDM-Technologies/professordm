import Link from "next/link";
import { AiDisclosure } from "@/components/ai-disclosure";
import { entryExcerpt, entryTitle, type KnowledgeEntry } from "@/lib/knowledge/search";

export function EntryCard({ entry }: { entry: KnowledgeEntry }) {
  const title = entryTitle(entry);
  return (
    <article className="rounded-2xl border border-pdm-border bg-pdm-panel p-4">
      <h3 className="font-semibold text-pdm-ink">
        <Link href={`/entry/${entry.id}`} className="underline-offset-4 hover:underline">
          {title}
        </Link>
      </h3>
      <p className="mt-2 text-sm text-pdm-muted">{entryExcerpt(entry.content)}</p>
      {entry.tags && entry.tags.length > 0 ? (
        <ul className="mt-3 flex flex-wrap gap-2 text-xs" aria-label={`Topics for ${title}`}>
          {entry.tags.map((tag) => (
            <li key={tag} className="rounded-full bg-pdm-tint px-2 py-0.5 font-semibold text-pdm-accent-strong">
              {tag}
            </li>
          ))}
        </ul>
      ) : null}
      <AiDisclosure variant="short" />
    </article>
  );
}
