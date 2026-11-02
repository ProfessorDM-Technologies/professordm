// Pure: decides what an inbox card says (docs/plans/creator-inbox-spec.md section 6). No Supabase here.
import { COVERAGE_LABELS, coverageLabel, noDraftReasonLabel } from "@/lib/inbox/labels";

export type CardTone = "progress" | "danger" | "accent" | "neutral";

export type CardState = {
  label: string;
  tone: CardTone;
  hint: string;
  /** Visible action text. Null while the AI is drafting: the card is not clickable yet. */
  action: string | null;
};

export type CardQuestion = { status: string; openFlagIds: readonly string[] };
export type CardDraft = { status: string | null; coverage: string | null; reason: string | null };
export type CardSend = { status: string | null };

/** First match wins, in the order of the table in section 6. */
export function cardState(question: CardQuestion, draft: CardDraft | null, lastSend: CardSend | null): CardState {
  if (question.status === "paid" || question.status === "drafting") {
    return { label: "AI is drafting", tone: "progress", hint: "Usually ready in under 20 seconds.", action: null };
  }
  if (question.status === "approved" || question.status === "delivering") {
    return { label: "Sending", tone: "progress", hint: "Delivering to Instagram…", action: "View" };
  }
  if (question.openFlagIds.length > 0) {
    return {
      label: "Review flag first",
      tone: "danger",
      hint: "A safety check flagged this. Review it before answering.",
      action: "Review",
    };
  }
  if (lastSend?.status === "failed") {
    return { label: "Send failed", tone: "danger", hint: "Your answer was saved. Open it to try again.", action: "Try again" };
  }
  if (!draft) {
    return { label: "AI unavailable", tone: "neutral", hint: "The AI couldn't draft this. Answer it yourself.", action: "Answer" };
  }
  if (draft.status === "ready") {
    return {
      label: "Draft ready",
      tone: "accent",
      hint: coverageLabel(draft.coverage) ?? "Review the AI draft before you send it.",
      action: "Review & answer",
    };
  }
  if (draft.status === "no_draft") {
    return {
      label: "Answer by hand",
      tone: "neutral",
      hint: noDraftReasonLabel(draft.reason) ?? COVERAGE_LABELS.none,
      action: "Answer",
    };
  }
  // Any other draft status (not expected while waiting for the creator): let her open and answer it.
  return { label: "Waiting for your answer", tone: "neutral", hint: "Open it to write your answer.", action: "Answer" };
}
