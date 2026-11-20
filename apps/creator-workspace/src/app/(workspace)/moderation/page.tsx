import type { Metadata } from "next";
import Link from "next/link";
import { DecisionButtons } from "@/components/inbox/decision-buttons";
import { RealtimeRefresh } from "@/components/inbox/realtime-refresh";
import { LocalTime } from "@/components/local-time";
import { EmptyState } from "@/components/empty-state";
import { PageHeader, PageSection } from "@/components/page-section";
import { QueueTabs } from "@/components/queue-tabs";
import { getSessionUser } from "@/lib/auth/session";
import { categoryLabel, flagLabel } from "@/lib/inbox/labels";
import { listDecisionMessages, listOpenFlags } from "@/lib/inbox/questions";

export const metadata: Metadata = {
  title: "Moderation",
};

function LoadError({ children }: { children: string }) {
  return (
    <p role="alert" className="rounded-2xl border border-pdm-danger-line bg-pdm-danger-bg p-4 text-sm font-medium text-pdm-danger-ink">
      {children}
    </p>
  );
}

export default async function ModerationPage() {
  const [session, flagged, decisions] = await Promise.all([getSessionUser(), listOpenFlags(), listDecisionMessages()]);
  const isAdmin = session?.role === "admin";

  return (
    <div className="space-y-6">
      <RealtimeRefresh />
      <PageHeader title="Moderation" description="Flagged questions and answers that need a review." />
      <QueueTabs current="/moderation" />

      <PageSection id="flagged-questions" title="Flagged questions">
        {flagged.error ? (
          <LoadError>Couldn&apos;t load flagged questions. Try again.</LoadError>
        ) : flagged.questions.length === 0 ? (
          <EmptyState icon="shield" tone="teal" title="No flagged questions">
            Questions a safety check flags wait here for you before anything is sent.
          </EmptyState>
        ) : (
          <ul className="space-y-3">
            {flagged.questions.map((question) => (
              <li key={question.id}>
                <Link
                  href={`/inbox/question/${question.id}`}
                  className="pdm-lift block space-y-2 rounded-2xl border border-pdm-border bg-pdm-panel p-4 hover:border-pdm-accent"
                >
                  <p className="font-semibold">
                    {question.follower?.username ? `@${question.follower.username}` : "Unknown sender"}
                  </p>
                  <p className="line-clamp-2 text-sm text-pdm-ink">{question.questionText}</p>
                  <div className="flex flex-wrap items-end justify-between gap-3">
                    <ul aria-label="Safety flags" className="flex flex-wrap gap-2 text-xs">
                      {question.flags.map((flag) => (
                        <li key={flag.id} className="rounded-full bg-pdm-danger-bg px-2 py-0.5 font-semibold text-pdm-danger-ink">
                          {flagLabel(flag)}
                          <span className="font-normal"> · {flag.targetType === "draft" ? "on the AI draft" : "on the message"}</span>
                        </li>
                      ))}
                    </ul>
                    <span className="pdm-press inline-flex min-h-11 items-center rounded-full bg-pdm-accent px-4 text-sm font-semibold text-pdm-on-accent">
                      Review
                    </span>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </PageSection>

      <PageSection id="needs-decision" title="Needs your decision">
        {decisions.error ? (
          <LoadError>Couldn&apos;t load messages that need your decision. Try again.</LoadError>
        ) : decisions.messages.length === 0 ? (
          <EmptyState icon="shield" tone="teal" title="Nothing to decide">
            Messages the AI hands to you, like safety concerns, wait here for your call.
          </EmptyState>
        ) : (
          <ul className="space-y-3">
            {decisions.messages.map((message) => (
              <li key={message.id} className="space-y-3 rounded-2xl border border-pdm-border bg-pdm-panel p-4">
                <div className="space-y-2">
                  <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                    <p className="font-semibold">
                      {message.follower.username ? `@${message.follower.username}` : "Unknown sender"}
                    </p>
                    <LocalTime value={message.receivedAt} className="text-xs text-pdm-muted" />
                  </div>
                  <p className="line-clamp-2 text-sm text-pdm-ink">{message.text || "(No text — attachment only)"}</p>
                  <p className="text-xs">
                    <span
                      className={`rounded-full px-2 py-0.5 font-semibold ${
                        message.category === "safety_concern" ? "bg-pdm-danger-bg text-pdm-danger-ink" : "bg-pdm-subtle text-pdm-ink"
                      }`}
                    >
                      {categoryLabel(message.category)}
                    </span>
                  </p>
                  {message.reason ? (
                    <p className="text-sm text-pdm-muted">
                      <span className="font-medium text-pdm-ink">AI note: </span>
                      {message.reason}
                    </p>
                  ) : null}
                  <Link
                    href={`/inbox/${message.follower.id}`}
                    className="inline-flex min-h-11 items-center text-sm font-medium text-pdm-accent-strong underline underline-offset-4"
                  >
                    Open the conversation to reply →
                  </Link>
                </div>
                <DecisionButtons messageId={message.id} />
              </li>
            ))}
          </ul>
        )}
      </PageSection>

      <PageSection id="flagged-answers" title="Answers with the ProfessorDM team">
        <EmptyState icon="shield" tone="teal" title="Nothing held for review">
          If the ProfessorDM team holds one of your answers, it shows here with their feedback.
        </EmptyState>
      </PageSection>

      <PageSection id="flagged-knowledge" title="Flagged knowledge entries">
        <EmptyState icon="book" tone="teal" title="No flagged entries">
          Nothing in your Knowledge Database is flagged.
        </EmptyState>
      </PageSection>

      {isAdmin ? (
        <PageSection id="admin-review" title="ProfessorDM team review">
          <EmptyState icon="shield" tone="teal" title="Nothing waiting for review">
            Flagged answers from every creator come here for you to approve or send back with feedback.
          </EmptyState>
        </PageSection>
      ) : null}
    </div>
  );
}
