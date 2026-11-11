"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { StatusChip } from "@/components/inbox/status-chip";
import { buttonClass } from "@/components/ui/button-styles";
import { railModeFor, shortAgo, type ConversationSummary } from "@/lib/inbox/conversations";
import type { CardTone } from "@/lib/inbox/question-state";

export type RailQuestion = {
  id: string;
  username: string | null;
  text: string;
  at: string | null;
  label: string;
  tone: CardTone;
  /** False while the AI is drafting: the question can't be opened yet. */
  openable: boolean;
};

type Mode = "chats" | "questions";

function handle(username: string | null) {
  return username ? `@${username}` : "Unknown sender";
}

function Initial({ username }: { username: string | null }) {
  return (
    <span
      aria-hidden="true"
      className="flex size-9 shrink-0 items-center justify-center rounded-full bg-pdm-primary-tint font-display text-sm font-bold text-pdm-primary"
    >
      {(username?.[0] ?? "?").toUpperCase()}
    </span>
  );
}

const ROW =
  "flex min-h-14 items-center gap-3 rounded-lg px-2.5 py-2 motion-safe:transition-colors aria-[current=page]:bg-pdm-primary-tint hover:bg-pdm-canvas aria-[current=page]:hover:bg-pdm-primary-tint";

function Time({ at }: { at: string | null }) {
  if (!at) return null;
  return (
    <time dateTime={at} suppressHydrationWarning className="shrink-0 text-xs text-pdm-muted">
      {shortAgo(at)}
    </time>
  );
}

/** The list inside the rail and the phone drawer: a Chats | Questions switch and one row per chat or question. */
function RailList({
  conversations,
  questions,
  initialMode,
  onNavigate,
}: {
  conversations: ConversationSummary[];
  questions: RailQuestion[];
  initialMode: Mode;
  onNavigate?: () => void;
}) {
  const pathname = usePathname();
  const [mode, setMode] = useState<Mode>(initialMode);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div role="tablist" aria-label="Switch list" className="m-2 grid grid-cols-2 gap-1 rounded-full bg-pdm-canvas p-1 ring-1 ring-pdm-border">
        {(["chats", "questions"] as const).map((value) => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={mode === value}
            onClick={() => setMode(value)}
            className="min-h-9 rounded-full text-xs font-semibold text-pdm-muted motion-safe:transition-colors aria-selected:bg-pdm-card aria-selected:text-pdm-primary aria-selected:shadow-sm"
          >
            {value === "chats" ? `Chats (${conversations.length})` : `Questions (${questions.length})`}
          </button>
        ))}
      </div>

      <div role="tabpanel" className="min-h-0 flex-1 overflow-y-auto px-2 pb-2 [scrollbar-width:thin]">
        {mode === "chats" ? (
          conversations.length === 0 ? (
            <p className="p-3 text-sm text-pdm-muted">No conversations yet.</p>
          ) : (
            <ul className="space-y-0.5">
              {conversations.map((chat) => {
                const href = `/inbox/${chat.followerId}`;
                return (
                  <li key={chat.followerId}>
                    <Link href={href} aria-current={pathname === href ? "page" : undefined} onClick={onNavigate} className={ROW}>
                      <Initial username={chat.username} />
                      <span className="min-w-0 flex-1">
                        <span className="flex items-baseline justify-between gap-2">
                          <span className="truncate text-sm font-semibold text-pdm-ink">{handle(chat.username)}</span>
                          <Time at={chat.lastAt} />
                        </span>
                        <span className="block truncate text-xs text-pdm-muted">{chat.lastText ?? "Attachment"}</span>
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          )
        ) : questions.length === 0 ? (
          <p className="p-3 text-sm text-pdm-muted">You&apos;re all caught up.</p>
        ) : (
          <ul className="space-y-0.5">
            {questions.map((question) => {
              const href = `/inbox/question/${question.id}`;
              const body = (
                <>
                  <Initial username={question.username} />
                  <span className="min-w-0 flex-1 space-y-1">
                    <span className="flex items-baseline justify-between gap-2">
                      <span className="truncate text-sm font-semibold text-pdm-ink">{handle(question.username)}</span>
                      <Time at={question.at} />
                    </span>
                    <span className="block truncate text-xs text-pdm-muted">{question.text}</span>
                    <StatusChip label={question.label} tone={question.tone} />
                  </span>
                </>
              );
              return (
                <li key={question.id}>
                  {question.openable ? (
                    <Link href={href} aria-current={pathname === href ? "page" : undefined} onClick={onNavigate} className={ROW}>
                      {body}
                    </Link>
                  ) : (
                    <div className={`${ROW} opacity-70`}>{body}</div>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}

/**
 * Inbox chat switcher (UI v2 spec, requirement 8). Desktop: a sticky rail beside the conversation or question.
 * Phones and tablets: a "Chats" button that opens the same list in a left drawer.
 * It lives in the (detail) layout, so it stays mounted while you move between chats.
 */
export function ChatRail({ conversations, questions }: { conversations: ConversationSummary[]; questions: RailQuestion[] }) {
  const pathname = usePathname();
  const mode = railModeFor(pathname) ?? "chats";
  const dialogRef = useRef<HTMLDialogElement>(null);

  // Close the drawer once a navigation from it lands.
  useEffect(() => {
    dialogRef.current?.close();
  }, [pathname]);

  return (
    <>
      <aside
        aria-label="Inbox chats"
        className="sticky top-24 hidden h-[calc(100dvh-10rem)] min-h-[24rem] overflow-hidden rounded-xl border border-pdm-border bg-pdm-card lg:block"
      >
        {/* key: switch the default tab when moving between a chat and a question. */}
        <RailList key={mode} conversations={conversations} questions={questions} initialMode={mode} />
      </aside>

      <div className="mb-3 lg:hidden">
        <button type="button" onClick={() => dialogRef.current?.showModal()} className={buttonClass("secondary", "sm")}>
          <svg aria-hidden="true" viewBox="0 0 20 20" className="size-4" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round">
            <path d="M3 5h14M3 10h14M3 15h9" />
          </svg>
          {mode === "chats" ? "All chats" : "All questions"}
        </button>
        <dialog
          ref={dialogRef}
          aria-label="Inbox chats"
          onClick={(event) => {
            // A click on the backdrop (the dialog element itself) closes the drawer.
            if (event.target === event.currentTarget) event.currentTarget.close();
          }}
          className="fixed inset-y-0 left-0 m-0 h-dvh max-h-none w-[min(22rem,88vw)] border-r border-pdm-border bg-pdm-card p-0 text-pdm-ink backdrop:bg-pdm-ink/40 backdrop:backdrop-blur-sm motion-safe:transition-[translate,display,overlay] motion-safe:transition-discrete motion-safe:duration-200 motion-safe:starting:-translate-x-full"
        >
          <div className="flex h-full flex-col">
            <div className="flex items-center justify-between border-b border-pdm-border px-4 py-3">
              <p className="font-display text-sm font-semibold text-pdm-heading">Inbox</p>
              <button
                type="button"
                onClick={() => dialogRef.current?.close()}
                aria-label="Close"
                className={buttonClass("ghost", "sm", "size-9 px-0")}
              >
                <svg aria-hidden="true" viewBox="0 0 20 20" className="size-4" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinecap="round">
                  <path d="m5 5 10 10M15 5 5 15" />
                </svg>
              </button>
            </div>
            <div className="min-h-0 flex-1">
              <RailList key={mode} conversations={conversations} questions={questions} initialMode={mode} />
            </div>
          </div>
        </dialog>
      </div>
    </>
  );
}
