import Link from "next/link";
import { LocalTime } from "@/components/local-time";
import { StatusChip } from "@/components/inbox/status-chip";
import { cardState, waitLabel } from "@/lib/inbox/question-state";
import type { QueueQuestion } from "@/lib/inbox/questions";

function footerParts(question: QueueQuestion) {
  const parts: string[] = [];
  if (question.draft && question.draft.sourceCount > 0) {
    parts.push(`${question.draft.sourceCount} ${question.draft.sourceCount === 1 ? "source" : "sources"}`);
  }
  parts.push(question.source === "knowledge_app" ? "Knowledge app" : "Instagram");
  // Payment is stubbed this milestone: no price means a test payment.
  if (question.priceCents === null) parts.push("Paid (test)");
  return parts;
}

// One inbox card (spec section 8.1). The whole card is one link, with the action as visible text.
export function QuestionCard({ question, now }: { question: QueueQuestion; now: number }) {
  const state = cardState(question, question.draft, question.lastSend);
  const username = question.follower?.username ? `@${question.follower.username}` : "Unknown sender";
  const waited = waitLabel(question.paidAt, now);
  const drafting = state.action === null;

  const body = (
    <>
      <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
        <p className="font-semibold">{username}</p>
        <div className="flex items-center gap-3">
          {waited && question.paidAt ? (
            <span className="group/time relative text-xs text-pdm-muted">
              {waited}
              <span
                aria-hidden="true"
                className="absolute top-full right-0 z-10 mt-1 hidden whitespace-nowrap rounded border border-pdm-border bg-white px-2 py-1 text-pdm-ink group-hover/time:block"
              >
                <LocalTime value={question.paidAt} />
              </span>
            </span>
          ) : null}
          <StatusChip label={state.label} tone={state.tone} />
        </div>
      </div>

      {drafting ? (
        <div aria-hidden="true" className="space-y-2 py-1">
          <div className="h-3 w-11/12 rounded bg-stone-200 motion-safe:animate-pulse" />
          <div className="h-3 w-2/3 rounded bg-stone-200 motion-safe:animate-pulse" />
        </div>
      ) : (
        <p className="line-clamp-2 text-sm text-pdm-ink">{question.questionText}</p>
      )}

      <div className="flex flex-wrap items-end justify-between gap-3">
        <p className="text-xs text-pdm-muted">{[state.hint, ...footerParts(question)].join(" · ")}</p>
        {state.action ? (
          <span className="inline-flex min-h-11 items-center rounded-lg bg-pdm-accent px-4 text-sm font-semibold text-white group-hover/card:bg-pdm-accent-strong">
            {state.action}
          </span>
        ) : null}
      </div>
    </>
  );

  return (
    <li>
      {drafting ? (
        <div className="space-y-2 rounded-lg border border-pdm-border bg-white p-4">{body}</div>
      ) : (
        <Link
          href={`/inbox/question/${question.id}`}
          className="group/card block space-y-2 rounded-lg border border-pdm-border bg-white p-4 hover:border-pdm-accent"
        >
          {body}
        </Link>
      )}
    </li>
  );
}
