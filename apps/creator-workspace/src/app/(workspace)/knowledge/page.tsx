import type { Metadata } from "next";
import { PublishButton } from "@/components/knowledge/publish-button";
import { PageHeader, PageSection } from "@/components/page-section";
import { Placeholder } from "@/components/placeholder";
import { entryTitle } from "@/lib/knowledge/answer-entries";
import { listAnswerEntries, type AnswerEntry } from "@/lib/knowledge/queries";

export const metadata: Metadata = {
  title: "Knowledge Database",
};

function EntryCard({ entry }: { entry: AnswerEntry }) {
  return (
    <li className="space-y-3 rounded-lg border border-pdm-border bg-white p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <p className="font-semibold">{entryTitle(entry)}</p>
        <span
          className={`rounded-full px-2 py-0.5 text-xs font-semibold ${
            entry.published ? "bg-green-100 text-green-800" : "bg-stone-100 text-pdm-ink"
          }`}
        >
          {entry.published ? "Published" : "Private"}
        </span>
      </div>
      {entry.content ? <p className="line-clamp-3 whitespace-pre-wrap text-sm text-pdm-ink">{entry.content}</p> : null}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <ul aria-label="Tags" className="flex flex-wrap gap-2 text-xs">
          {entry.tags.map((tag) => (
            <li key={tag} className="rounded-full bg-pdm-tint px-2 py-0.5 font-semibold text-pdm-accent-strong">
              {tag}
            </li>
          ))}
        </ul>
        <PublishButton entryId={entry.id} published={entry.published} />
      </div>
    </li>
  );
}

export default async function KnowledgePage() {
  const { entries, error } = await listAnswerEntries();

  return (
    <div className="space-y-8">
      <PageHeader
        title="Knowledge Database"
        description="Your past answers and facts. The AI searches these first when drafting."
      />

      <PageSection id="entries" title="Answers from your questions">
        <p className="text-sm text-pdm-muted">
          Answers you send are saved here as private entries. Publish the ones you want in the Knowledge app.
        </p>
        {error ? (
          <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm font-medium text-red-800">
            Couldn&apos;t load your answers. Try again.
          </p>
        ) : entries.length === 0 ? (
          <Placeholder>No saved answers yet. They appear here after you send an answer.</Placeholder>
        ) : (
          <ul className="space-y-3">
            {entries.map((entry) => (
              <EntryCard key={entry.id} entry={entry} />
            ))}
          </ul>
        )}
      </PageSection>

      <PageSection id="add" title="Add a fact">
        <Placeholder>A form to add a new fact by hand will appear here.</Placeholder>
      </PageSection>
    </div>
  );
}
