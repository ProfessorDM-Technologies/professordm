import type { Metadata } from "next";
import Link from "next/link";
import { RealtimeRefresh } from "@/components/inbox/realtime-refresh";
import { LocalTime } from "@/components/local-time";
import { PageHeader, PageSection } from "@/components/page-section";
import { Placeholder } from "@/components/placeholder";
import { QueueTabs } from "@/components/queue-tabs";
import { buttonClass } from "@/components/ui/button-styles";
import { getSessionUser } from "@/lib/auth/session";
import { categoryLabel, flagLabel } from "@/lib/inbox/labels";
import { listDecisionMessages, listOpenFlags } from "@/lib/inbox/questions";

export const metadata: Metadata = {
  title: "Moderation",
};

function LoadError({ children }: { children: string }) {
  return (
    <p role="alert" className="rounded-xl border border-pdm-danger-border bg-pdm-danger-tint p-4 text-sm font-medium text-pdm-danger-text">
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
          <Placeholder>No flagged questions. Questions flagged by a safety check appear here.</Placeholder>
        ) : (
          <ul className="space-y-3">
            {flagged.questions.map((question) => (
              <li key={question.id}>
                <Link
                  href={`/inbox/question/${question.id}`}
                  className="group/card block space-y-2 rounded-xl border border-pdm-border bg-white p-4 motion-safe:transition-colors hover:border-pdm-primary"
                >
                  <p className="font-semibold">
                    {question.follower?.username ? `@${question.follower.username}` : "Unknown sender"}
                  </p>
                  <p className="line-clamp-2 text-sm text-pdm-ink">{question.questionText}</p>
                  <div className="flex flex-wrap items-end justify-between gap-3">
                    <ul aria-label="Safety flags" className="flex flex-wrap gap-2 text-xs">
                      {question.flags.map((flag) => (
                        <li key={flag.id} className="rounded-full bg-pdm-danger-tint px-2 py-0.5 font-semibold text-pdm-danger-text">
                          {flagLabel(flag)}
                          <span className="font-normal"> · {flag.targetType === "draft" ? "on the AI draft" : "on the message"}</span>
                        </li>
                      ))}
                    </ul>
                    <span className={buttonClass("primary", "md", "group-hover/card:bg-pdm-primary-hover")}>
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
          <Placeholder>Nothing to decide. Messages the AI hands to you, like safety concerns, appear here.</Placeholder>
        ) : (
          <ul className="space-y-3">
            {decisions.messages.map((message) => (
              <li key={message.id}>
                <Link
                  href={`/inbox/${message.follower.id}`}
                  className="block space-y-2 rounded-xl border border-pdm-border bg-white p-4 motion-safe:transition-colors hover:border-pdm-primary"
                >
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
                        message.category === "safety_concern"
                          ? "bg-pdm-danger-tint text-pdm-danger-text"
                          : "bg-white text-pdm-ink ring-1 ring-pdm-border"
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
                  <p className="text-sm font-medium text-pdm-primary underline underline-offset-4">
                    Open the conversation to reply or leave it
                  </p>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </PageSection>

      <PageSection id="flagged-answers" title="Answers with the ProfessorDM team">
        <Placeholder>Your answers held for ProfessorDM review, with any feedback.</Placeholder>
      </PageSection>

      <PageSection id="flagged-knowledge" title="Flagged knowledge entries">
        <Placeholder>Knowledge entries flagged by the weekly safety review.</Placeholder>
      </PageSection>

      {isAdmin ? (
        <PageSection id="admin-review" title="ProfessorDM team review">
          <Placeholder>Admin only: approve flagged answers or send them back with feedback.</Placeholder>
        </PageSection>
      ) : null}
    </div>
  );
}
