"use client";

import Link from "next/link";
import { useActionState, useEffect, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { FlagPanel } from "@/components/inbox/flag-panel";
import { StatusChip } from "@/components/inbox/status-chip";
import { buttonClass } from "@/components/ui/button-styles";
import { approveAnswer, type ApproveAnswerState } from "@/lib/inbox/actions";
import { MAX_TAGS, answerBytes, changeRatio, checkSendGate, normalizeAnswer, parseTags } from "@/lib/inbox/answer";
import type { QuestionFlag } from "@/lib/inbox/questions";
import { MAX_REPLY_BYTES, MAX_REPLY_LENGTH } from "@/lib/inbox/reply";

const INITIAL_STATE: ApproveAnswerState = { status: "idle" };
const UNDO_MS = 10_000;
const METER_DEBOUNCE_MS = 300;

export type ComposerQuestion = {
  id: string;
  status: string;
  source: string;
  /** The Instagram DM the answer replies to. */
  originMessageId: string | null;
  draftId: string | null;
  aiText: string | null;
  /** Her last version, saved by the send API when Instagram didn't accept it. */
  savedText: string | null;
};

function notAnswerableReason(question: ComposerQuestion): ReactNode | null {
  if (question.status === "paid" || question.status === "drafting") {
    return "The AI is still drafting. This page updates as soon as the draft is ready.";
  }
  if (question.status === "approved" || question.status === "delivering") {
    return "This answer is being sent to Instagram.";
  }
  if (["delivered", "accepted", "closed"].includes(question.status)) {
    return (
      <>
        This question has been answered.{" "}
        <Link href="/sent" className="font-medium text-pdm-primary underline underline-offset-4">
          See it in Sent
        </Link>
      </>
    );
  }
  if (question.status !== "awaiting_creator") {
    return "This question can't be answered right now.";
  }
  if (question.source !== "instagram" || !question.originMessageId) {
    return "This question didn't come from an Instagram DM, so it can't be answered here yet.";
  }
  return null;
}

/**
 * The answer workspace layout plus the composer (spec sections 8.2 and 8.3). The flag checkboxes on the left
 * feed the send gate on the right, so this client component owns both. Context and sources are rendered on
 * the server and passed in.
 */
export function AnswerWorkspace({
  question,
  username,
  flags,
  context,
  sources,
  nextQuestionId,
}: {
  question: ComposerQuestion;
  username: string;
  flags: QuestionFlag[];
  context: ReactNode;
  sources: ReactNode;
  nextQuestionId: string | null;
}) {
  const [acknowledged, setAcknowledged] = useState<ReadonlySet<string>>(() => new Set());
  // One id per send press. The action says when a new one is needed (nextRequestId, spec section 8.3).
  const [requestId, setRequestId] = useState(() => crypto.randomUUID());

  const [state, formAction, pending] = useActionState(async (prev: ApproveAnswerState, formData: FormData) => {
    const result = await approveAnswer(prev, formData);
    if (result.status !== "idle") setRequestId(result.nextClientRequestId);
    return result;
  }, INITIAL_STATE);

  const openFlagIds = flags.filter((flag) => flag.status === "open").map((flag) => flag.id);
  const done = state.status === "sent" || state.status === "pending";
  const blocked = notAnswerableReason(question);
  // Once she has pressed send, keep the form (and her text) on screen whatever the question status becomes.
  const showForm = !done && (blocked === null || pending || state.status === "error");

  const toggleFlag = (flagId: string, checked: boolean) =>
    setAcknowledged((current) => {
      const next = new Set(current);
      if (checked) next.add(flagId);
      else next.delete(flagId);
      return next;
    });

  return (
    <div className="grid gap-6 xl:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
      <div className="space-y-6">
        {context}
        <FlagPanel
          flags={flags}
          acknowledged={acknowledged}
          onToggle={showForm ? toggleFlag : undefined}
          disabled={pending}
        />
      </div>

      <div className="space-y-6">
        {done ? (
          <div
            ref={(element) => element?.focus()}
            tabIndex={-1}
            role="status"
            className="space-y-3 rounded-xl border border-pdm-success/30 bg-pdm-success-tint p-4"
          >
            <p className="font-semibold text-pdm-success-text">
              {state.status === "sent"
                ? `Answer sent to ${username} on Instagram`
                : `Your answer to ${username} is on its way to Instagram. This page updates when it's delivered.`}
            </p>
            <div className="flex flex-wrap gap-3">
              {nextQuestionId ? (
                <Link
                  href={`/inbox/question/${nextQuestionId}`}
                  className={buttonClass("primary", "md", "px-5")}
                >
                  Next question →
                </Link>
              ) : null}
              <Link
                href="/inbox"
                className={buttonClass("secondary", "md", "px-5")}
              >
                Back to inbox
              </Link>
            </div>
          </div>
        ) : showForm ? (
          <AnswerForm
            // A new draft (for example when drafting finishes) starts a fresh editor.
            key={question.draftId ?? "no-draft"}
            question={question}
            username={username}
            requestId={requestId}
            openFlagIds={openFlagIds}
            acknowledgedFlagIds={openFlagIds.filter((id) => acknowledged.has(id))}
            formAction={formAction}
            pending={pending}
            error={state.status === "error" ? state.message : null}
          />
        ) : (
          <p className="rounded-xl border border-pdm-border bg-pdm-card p-4 text-sm text-pdm-muted">{blocked}</p>
        )}
        {sources}
      </div>
    </div>
  );
}

function AnswerForm({
  question,
  username,
  requestId,
  openFlagIds,
  acknowledgedFlagIds,
  formAction,
  pending,
  error,
}: {
  question: ComposerQuestion;
  username: string;
  requestId: string;
  openFlagIds: string[];
  acknowledgedFlagIds: string[];
  formAction: (formData: FormData) => void;
  pending: boolean;
  error: string | null;
}) {
  const { aiText, savedText } = question;
  const initialText = savedText ?? aiText ?? "";
  const [text, setText] = useState(initialText);
  const [tags, setTags] = useState<string[]>([]);
  const [tagInput, setTagInput] = useState("");
  const [tagError, setTagError] = useState<string | null>(null);
  const [undoText, setUndoText] = useState<string | null>(null);
  const [ratio, setRatio] = useState(() => (aiText ? changeRatio(aiText, initialText) : 0));
  const dialogRef = useRef<HTMLDialogElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  const gate = checkSendGate({ text, aiText, tags, openFlagIds, acknowledgedFlagIds });
  const bytes = answerBytes(text.trim());
  const edited = aiText !== null && normalizeAnswer(text) !== normalizeAnswer(aiText);
  const unsaved = text !== initialText;

  // "Your voice" meter, debounced so it doesn't jump on every key.
  useEffect(() => {
    if (aiText === null) return;
    const timer = setTimeout(() => setRatio(changeRatio(aiText, text)), METER_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [aiText, text]);

  useEffect(() => {
    if (undoText === null) return;
    const timer = setTimeout(() => setUndoText(null), UNDO_MS);
    return () => clearTimeout(timer);
  }, [undoText]);

  // Warn before leaving with an edited answer that wasn't sent.
  useEffect(() => {
    if (!unsaved) return;
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [unsaved]);

  const openConfirm = () => {
    if (gate.ok && !pending) dialogRef.current?.showModal();
  };

  const addTags = (raw: string) => {
    const parsed = parseTags([...tags, ...raw.split(",")]);
    if (!parsed.ok) {
      setTagError(parsed.error);
      return false;
    }
    setTags(parsed.tags);
    setTagError(null);
    return true;
  };

  const onTagKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Enter" || event.key === ",") {
      event.preventDefault();
      if (tagInput.trim() && addTags(tagInput)) setTagInput("");
    } else if (event.key === "Backspace" && tagInput === "" && tags.length) {
      setTags(tags.slice(0, -1));
      setTagError(null);
    }
  };

  const onTextKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
      event.preventDefault();
      openConfirm();
    }
  };

  const resetToDraft = () => {
    if (aiText === null) return;
    setUndoText(text);
    setText(aiText);
  };

  const undoReset = () => {
    if (undoText === null) return;
    setText(undoText);
    setUndoText(null);
  };

  const statusLine = savedText
    ? "Your last version · it wasn't delivered"
    : aiText
      ? "AI draft · edit it into your own words"
      : "No AI draft · write your answer";

  const counterStyle =
    bytes > MAX_REPLY_BYTES ? "font-semibold text-pdm-danger-text" : bytes >= 900 ? "font-semibold text-pdm-primary" : "text-pdm-muted";

  return (
    <form
      action={formAction}
      onSubmit={() => dialogRef.current?.close()}
      className="space-y-4 rounded-xl border border-pdm-border bg-pdm-card p-4"
    >
      <input type="hidden" name="question_id" value={question.id} />
      <input type="hidden" name="inbound_message_id" value={question.originMessageId ?? ""} />
      <input type="hidden" name="client_request_id" value={requestId} />
      {tags.map((tag) => (
        <input key={tag} type="hidden" name="tags" value={tag} />
      ))}
      {acknowledgedFlagIds.map((flagId) => (
        <input key={flagId} type="hidden" name="reviewed_flag_ids" value={flagId} />
      ))}

      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-pdm-muted">{statusLine}</p>
        {pending ? <StatusChip label="Sending" tone="progress" /> : null}
      </div>

      <div className="space-y-2">
        <label htmlFor="answer-text" className="block font-medium">
          Your answer to {username}
        </label>
        <textarea
          id="answer-text"
          name="text"
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={onTextKeyDown}
          readOnly={pending}
          maxLength={MAX_REPLY_LENGTH}
          aria-describedby="answer-gate answer-counter"
          aria-invalid={error ? true : undefined}
          // Untouched AI draft = cyan; once the creator edits it, their voice = sage (spec section 6). The status line names the state too.
          className={`block min-h-48 w-full rounded-lg border border-pdm-border-strong p-3 text-base field-sizing-content motion-safe:transition-colors ${
            aiText === null ? "bg-pdm-card" : edited ? "bg-pdm-human" : "bg-pdm-ai-tint"
          }`}
        />
        <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
          <div className="flex flex-wrap items-center gap-3">
            {aiText !== null && edited ? (
              <button
                type="button"
                onClick={resetToDraft}
                disabled={pending}
                className="min-h-11 font-medium text-pdm-primary underline underline-offset-4"
              >
                Reset to AI draft
              </button>
            ) : null}
            {undoText !== null ? (
              <button
                type="button"
                onClick={undoReset}
                className="min-h-11 font-medium text-pdm-primary underline underline-offset-4"
              >
                Undo
              </button>
            ) : null}
          </div>
          <p id="answer-counter" className={counterStyle}>
            {bytes} / {MAX_REPLY_BYTES}
          </p>
        </div>
      </div>

      {aiText !== null ? (
        <div className="space-y-1">
          <div aria-hidden="true" className="h-1.5 overflow-hidden rounded-full bg-pdm-border/60">
            <div className="h-full rounded-full bg-pdm-success" style={{ width: `${Math.round(ratio * 100)}%` }} />
          </div>
          <p aria-live="polite" className="text-sm text-pdm-muted">
            {ratio === 0 ? "Not edited yet" : `You changed ${Math.round(ratio * 100)}% of the draft`}
          </p>
        </div>
      ) : null}

      <div className="space-y-2">
        <label htmlFor="answer-tags" className="block font-medium">
          Tags (1 to {MAX_TAGS})
        </label>
        <p id="answer-tags-help" className="text-sm text-pdm-muted">
          Tags help you find this answer later. Press Enter or a comma to add one.
        </p>
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-pdm-border-strong bg-pdm-card p-2">
          {tags.map((tag) => (
            <span key={tag} className="inline-flex items-center gap-1 rounded-full bg-pdm-primary-tint py-1 pr-1 pl-3 text-sm font-medium text-pdm-primary">
              {tag}
              <button
                type="button"
                onClick={() => setTags(tags.filter((current) => current !== tag))}
                disabled={pending}
                aria-label={`Remove tag ${tag}`}
                className="relative grid size-6 place-items-center rounded-full hover:bg-pdm-card after:absolute after:-inset-2.5 after:content-['']"
              >
                <svg aria-hidden="true" viewBox="0 0 12 12" className="size-3" fill="none" stroke="currentColor" strokeWidth="1.75">
                  <path d="M3 3l6 6M9 3l-6 6" />
                </svg>
              </button>
            </span>
          ))}
          <input
            id="answer-tags"
            type="text"
            value={tagInput}
            onChange={(event) => setTagInput(event.target.value)}
            onKeyDown={onTagKeyDown}
            onBlur={() => {
              if (tagInput.trim() && addTags(tagInput)) setTagInput("");
            }}
            readOnly={pending}
            disabled={tags.length >= MAX_TAGS}
            placeholder={tags.length >= MAX_TAGS ? "" : "e.g. calathea"}
            aria-describedby="answer-tags-help answer-tags-error"
            aria-invalid={tagError ? true : undefined}
            className="min-h-11 min-w-32 flex-1 bg-transparent px-1 text-base outline-offset-2"
          />
        </div>
        <p id="answer-tags-error" aria-live="polite" className="text-sm font-medium text-pdm-danger-text">
          {tagError}
        </p>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-pdm-border pt-4">
        <div id="answer-gate" aria-live="polite" className="text-sm">
          {error ? (
            <p role="alert" className="font-medium text-pdm-danger-text">
              {error}
            </p>
          ) : null}
          {gate.ok ? (
            <p className="text-pdm-muted">Ready to send. Nothing goes out until you confirm.</p>
          ) : (
            <p className="text-pdm-muted">{gate.missing.map((issue) => issue.message).join(" · ")}</p>
          )}
        </div>
        <button
          ref={triggerRef}
          type="button"
          onClick={openConfirm}
          disabled={!gate.ok || pending}
          className={buttonClass("primary", "md", "px-5")}
        >
          {pending ? "Sending…" : "Review & send"}
        </button>
      </div>

      <dialog
        ref={dialogRef}
        aria-labelledby="confirm-heading"
        onClose={() => triggerRef.current?.focus()}
        className="m-auto w-[min(36rem,calc(100vw-2rem))] rounded-xl border border-pdm-border bg-pdm-card p-0 text-pdm-ink shadow-[0_8px_24px_-12px_rgb(4_59_101/0.25)] backdrop:bg-pdm-ink/40 backdrop:backdrop-blur-sm"
      >
        <div className="space-y-4 p-5">
          <h2 id="confirm-heading" className="text-lg font-semibold">
            Send this answer to {username}?
          </h2>
          <p className="font-medium text-pdm-danger-text">This sends a DM on Instagram now.</p>
          <div className="max-h-[50vh] overflow-y-auto whitespace-pre-wrap rounded-lg border border-pdm-border bg-pdm-human p-3 text-sm">
            {text.trim()}
          </div>
          <p className="text-sm text-pdm-muted">Tags: {tags.join(", ")}</p>
          <div className="flex flex-wrap justify-end gap-3">
            <button
              type="button"
              onClick={() => dialogRef.current?.close()}
              className={buttonClass("secondary", "md", "px-5")}
            >
              Keep editing
            </button>
            <button
              type="submit"
              disabled={pending || !gate.ok}
              className={buttonClass("primary", "md", "px-5")}
            >
              Send answer
            </button>
          </div>
        </div>
      </dialog>
    </form>
  );
}
