import { flagLabel } from "@/lib/inbox/labels";
import type { QuestionFlag } from "@/lib/inbox/questions";

// Safety flags on the question's message and AI draft, in plain language (spec section 8.2).
// With onToggle, each open flag gets an "I've reviewed this" checkbox that feeds the send gate.
export function FlagPanel({
  flags,
  acknowledged,
  onToggle,
  disabled = false,
}: {
  flags: QuestionFlag[];
  acknowledged?: ReadonlySet<string>;
  onToggle?: (flagId: string, checked: boolean) => void;
  disabled?: boolean;
}) {
  if (flags.length === 0) return null;
  const open = flags.filter((flag) => flag.status === "open");

  return (
    <section
      aria-labelledby="flags-heading"
      className={`space-y-3 rounded-xl border p-4 ${
        open.length ? "border-pdm-danger-border bg-pdm-danger-tint" : "border-pdm-border bg-pdm-card"
      }`}
    >
      <div className="space-y-1">
        <h2 id="flags-heading" className="font-semibold">
          Safety flags
        </h2>
        <p className="text-sm text-pdm-muted">
          {open.length
            ? "A safety check flagged this. Read the question carefully and confirm each flag before you answer."
            : "You've reviewed every flag on this question."}
        </p>
      </div>
      <ul className="space-y-2">
        {flags.map((flag) => {
          const reviewed = flag.status !== "open";
          const where = flag.targetType === "draft" ? "On the AI draft" : "On the message";
          return (
            <li key={flag.id} className="rounded-lg border border-pdm-border bg-pdm-card p-3">
              <p className="font-medium">{flagLabel(flag)}</p>
              <p className="text-xs text-pdm-muted">{where}</p>
              {reviewed ? (
                <p className="mt-1 text-sm font-medium text-pdm-success-text">Reviewed by you</p>
              ) : onToggle ? (
                <label className="mt-1 flex min-h-11 cursor-pointer items-center gap-3 text-sm font-medium">
                  <input
                    type="checkbox"
                    className="size-5 accent-pdm-primary"
                    checked={acknowledged?.has(flag.id) ?? false}
                    onChange={(event) => onToggle(flag.id, event.target.checked)}
                    disabled={disabled}
                  />
                  I&apos;ve reviewed this
                </label>
              ) : (
                <p className="mt-1 text-sm font-medium text-pdm-danger-text">Not reviewed yet</p>
              )}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
