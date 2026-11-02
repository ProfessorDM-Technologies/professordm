import type { Metadata } from "next";
import Link from "next/link";
import { AnswerWorkspace } from "@/components/inbox/answer-composer";
import { RealtimeRefresh } from "@/components/inbox/realtime-refresh";
import { SourceList } from "@/components/inbox/source-list";
import { StatusChip } from "@/components/inbox/status-chip";
import { LocalTime } from "@/components/local-time";
import { RefreshButton } from "@/components/refresh-button";
import { categoryLabel } from "@/lib/inbox/labels";
import { cardState } from "@/lib/inbox/question-state";
import { getQuestion, listQuestions } from "@/lib/inbox/questions";

export const metadata: Metadata = {
  title: "Answer question",
};

const CATEGORY_STYLES: Record<string, string> = {
  expert_question: "bg-pdm-tint text-pdm-accent-strong",
  safety_concern: "bg-red-100 text-red-800",
};

// Same look as the conversation page bubbles: incoming bordered on the left, outgoing amber on the right.
function SmallBubble({ outgoing, label, text }: { outgoing: boolean; label: string; text: string }) {
  return (
    <li className={`flex ${outgoing ? "justify-end" : "justify-start"}`}>
      <div className={`flex max-w-[85%] flex-col space-y-1 ${outgoing ? "items-end text-right" : "items-start"}`}>
        <div
          className={`whitespace-pre-wrap rounded-2xl px-4 py-2 text-left text-sm ${
            outgoing ? "bg-pdm-accent text-white" : "border border-pdm-border bg-white text-pdm-ink"
          }`}
        >
          {text}
        </div>
        <p className="text-xs text-pdm-muted">{label}</p>
      </div>
    </li>
  );
}

// The answer workspace (spec section 8.2). Context on the left, the answer on the right;
// one column below lg in the order question, flags, composer, sources.
export default async function AnswerQuestionPage({ params }: PageProps<"/inbox/question/[id]">) {
  const { id } = await params;
  const [{ question, error }, inbox] = await Promise.all([getQuestion(id), listQuestions("inbox")]);

  const username = question.follower?.username ? `@${question.follower.username}` : "Unknown sender";
  const openFlagIds = question.flags.filter((flag) => flag.status === "open").map((flag) => flag.id);
  const state = cardState({ status: question.status, openFlagIds }, question.draft, question.lastSend);
  const origin = question.origin;
  // "Next question" after sending: the first other card in the inbox that can be opened.
  const nextQuestion = inbox.questions.find(
    (other) => other.id !== question.id && cardState(other, other.draft, other.lastSend).action !== null,
  );
  // Her saved text is only a "last version" when the send failed and the question came back to her.
  const savedText = question.status === "awaiting_creator" ? (question.draft?.finalText ?? null) : null;

  return (
    <article className="space-y-6">
      <RealtimeRefresh />
      <p>
        <Link href="/inbox" className="text-sm font-medium text-pdm-accent-strong underline underline-offset-4">
          Back to inbox
        </Link>
      </p>

      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-2xl font-semibold tracking-tight">{username}</h1>
            <StatusChip label={state.label} tone={state.tone} />
          </div>
          {question.follower ? (
            <Link
              href={`/inbox/${question.follower.id}`}
              className="text-sm font-medium text-pdm-accent-strong underline underline-offset-4"
            >
              View full conversation
            </Link>
          ) : null}
        </div>
        <RefreshButton />
      </div>

      {error ? (
        <p role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm font-medium text-red-800">
          Part of this question couldn&apos;t be loaded. Refresh before you answer.
        </p>
      ) : null}

      <AnswerWorkspace
        question={{
          id: question.id,
          status: question.status,
          source: question.source,
          originMessageId: question.originMessageId,
          draftId: question.draft?.id ?? null,
          aiText: question.draft?.aiText ?? null,
          savedText,
        }}
        username={username}
        flags={question.flags}
        nextQuestionId={nextQuestion?.id ?? null}
        context={
          <>
            <section aria-labelledby="question-heading" className="space-y-3 rounded-lg border border-pdm-border bg-white p-4">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <h2 id="question-heading" className="font-semibold">
                  The question
                </h2>
                {origin ? <LocalTime value={origin.receivedAt} className="text-xs text-pdm-muted" /> : null}
              </div>
              <p className="whitespace-pre-wrap text-pdm-ink">{origin?.text || question.questionText}</p>
              {origin ? (
                <div className="flex flex-wrap items-center gap-2 text-xs">
                  <span
                    className={`rounded-full px-2 py-0.5 font-semibold ${
                      (origin.category && CATEGORY_STYLES[origin.category]) ?? "bg-stone-100 text-pdm-ink"
                    }`}
                  >
                    {categoryLabel(origin.category)}
                  </span>
                  {origin.confidence !== null ? (
                    <span className="text-pdm-muted">{Math.round(origin.confidence * 100)}% confident</span>
                  ) : null}
                </div>
              ) : null}
              {origin?.reason ? (
                <details className="text-sm">
                  <summary className="min-h-11 cursor-pointer content-center font-medium text-pdm-accent-strong">
                    Why the AI sorted it this way
                  </summary>
                  <p className="whitespace-pre-wrap text-pdm-muted">{origin.reason}</p>
                </details>
              ) : null}
            </section>

            {question.clarifications.length ? (
              <section aria-labelledby="clarification-heading" className="space-y-3">
                <h2 id="clarification-heading" className="font-semibold">
                  Clarification
                </h2>
                <ol className="space-y-3">
                  {question.clarifications.flatMap((round) => [
                    round.prompt ? (
                      <SmallBubble key={`p-${round.id}`} outgoing label="The AI asked" text={round.prompt} />
                    ) : null,
                    round.reply ? (
                      <SmallBubble key={`r-${round.id}`} outgoing={false} label="They replied" text={round.reply} />
                    ) : null,
                  ])}
                </ol>
              </section>
            ) : null}

          </>
        }
        sources={
          <SourceList
            hasDraft={Boolean(question.draft?.aiText)}
            coverage={question.draft?.coverage ?? null}
            citations={question.draft?.citations ?? []}
            missingInfo={question.draft?.missingInfo ?? []}
          />
        }
      />
    </article>
  );
}
