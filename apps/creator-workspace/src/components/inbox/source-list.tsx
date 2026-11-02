import { coverageLabel } from "@/lib/inbox/labels";
import type { Citation } from "@/lib/inbox/questions";

const COVERAGE_STYLES: Record<string, string> = {
  high: "bg-pdm-tint text-pdm-accent-strong",
  partial: "bg-pdm-tint text-pdm-accent-strong",
  none: "bg-stone-100 text-pdm-ink",
};

// "Guide > Section > Subsection" as a breadcrumb with the last part bold.
function Breadcrumb({ title }: { title: string | null }) {
  const parts = (title ?? "").split(">").map((part) => part.trim()).filter(Boolean);
  if (parts.length === 0) return <span className="font-semibold">Untitled source</span>;
  const last = parts.at(-1);
  return (
    <span>
      {parts.slice(0, -1).map((part, index) => (
        <span key={index} className="text-pdm-muted">
          {part}
          <span aria-hidden="true"> › </span>
        </span>
      ))}
      <span className="font-semibold text-pdm-ink">{last}</span>
    </span>
  );
}

// The guide passages behind the AI draft and what the guides don't cover (spec section 8.2).
export function SourceList({
  hasDraft,
  coverage,
  citations,
  missingInfo,
}: {
  hasDraft: boolean;
  coverage: string | null;
  citations: Citation[];
  missingInfo: string[];
}) {
  const badge = coverageLabel(coverage);

  return (
    <section aria-labelledby="sources-heading" className="space-y-3 rounded-lg border border-pdm-border bg-white p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id="sources-heading" className="font-semibold">
          Sources
        </h2>
        {badge && coverage ? (
          <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${COVERAGE_STYLES[coverage]}`}>{badge}</span>
        ) : null}
      </div>

      {citations.length ? (
        <ol className="space-y-2">
          {citations.map((citation, index) => (
            <li key={`${citation.ref ?? "source"}-${index}`} className="space-y-1 border-t border-pdm-border pt-2 text-sm first:border-t-0 first:pt-0">
              <p>
                <Breadcrumb title={citation.title} />
              </p>
              {citation.supports ? <p className="text-pdm-muted">{citation.supports}</p> : null}
            </li>
          ))}
        </ol>
      ) : (
        <p className="text-sm text-pdm-muted">
          {hasDraft ? "The AI didn't use any of your guides for this one." : "There's no AI draft, so there are no sources."}
        </p>
      )}

      {missingInfo.length ? (
        <div className="space-y-1 rounded-lg bg-pdm-surface p-3 text-sm">
          <h3 className="font-semibold">What your guides don&apos;t cover</h3>
          <p className="text-pdm-muted">Your answer fills these gaps. Consider adding them to your Knowledge Database too:</p>
          <ul className="list-disc space-y-0.5 pl-5">
            {missingInfo.map((item, index) => (
              <li key={index}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
