import Link from "next/link";
import { LocalTime } from "@/components/local-time";
import { StatusChip } from "@/components/inbox/status-chip";
import { buttonClass } from "@/components/ui/button-styles";
import { cardState, waitLabel } from "@/lib/inbox/question-state";
import type { QueueQuestion } from "@/lib/inbox/questions";

type FooterPart = { text: string; money?: boolean };

function footerParts(question: QueueQuestion): FooterPart[] {
  const parts: FooterPart[] = [];
  if (question.draft && question.draft.sourceCount > 0) {
    parts.push({ text: `${question.draft.sourceCount} ${question.draft.sourceCount === 1 ? "source" : "sources"}` });
  }
  parts.push({ text: question.source === "knowledge_app" ? "Knowledge app" : "Instagram" });
  // Payment is stubbed this milestone: no price means a test payment. Gold marks money (spec section 3.1).
  if (question.priceCents === null) parts.push({ text: "Paid (test)", money: true });
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
          <div className="h-3 w-11/12 rounded bg-pdm-ai-tint motion-safe:animate-pulse" />
          <div className="h-3 w-2/3 rounded bg-pdm-ai-tint motion-safe:animate-pulse" />
        </div>
      ) : (
        <p className="line-clamp-2 text-sm text-pdm-ink">{question.questionText}</p>
      )}

      <div className="flex flex-wrap items-end justify-between gap-3">
        <p className="text-xs text-pdm-muted">
          {[{ text: state.hint }, ...footerParts(question)].map((part, index) => (
            <span key={part.text}>
              {index > 0 ? " · " : null}
              <span className={part.money ? "font-semibold text-pdm-money-text" : undefined}>{part.text}</span>
            </span>
          ))}
        </p>
        {state.action ? (
          <span className={buttonClass("primary", "md", "group-hover/card:bg-pdm-primary-hover")}>{state.action}</span>
        ) : null}
      </div>
    </>
  );

  return (
    <li>
      {drafting ? (
        <div className="space-y-2 rounded-xl border border-pdm-border bg-white p-4">{body}</div>
      ) : (
        <Link
          href={`/inbox/question/${question.id}`}
          className="group/card block space-y-2 rounded-xl border border-pdm-border bg-white p-4 motion-safe:transition-colors hover:border-pdm-primary"
        >
          {body}
        </Link>
      )}
    </li>
  );
}
