# Creator Inbox: answer AI-drafted questions (implementation spec)

Owners: **Part C** (Creator Workspace): **Ritvik**. **Part B** (send API): **Akshay**. **Part A** (migration 011):
Karthik, **already applied on staging** (PR #24). Reviewer: Karthik. Target: **Nov 13 milestone** (BASELINE section 4): *IG DM > triage > question in Creator Inbox >
draft > creator edits and approves > answer DM delivered. Moderation path is demonstrable. Payment is stubbed.*

Everything up to "draft saved" already works on staging (PR #23, verified Nov 2). This spec builds the last step:
**Kristin sees the question and the AI draft, makes the answer her own, and sends it to Instagram.**

---

## 0. Rules for the coding agent

1. **Only create or change the files listed in section 3.** Every other file is read-only. If a task seems to need a
   change anywhere else, **stop and ask Karthik**.
2. **No new dependencies.** Use what `apps/creator-workspace/package.json` already has: Next.js 16, React 19,
   Tailwind v4, `@supabase/ssr`, `@professordm/contracts`, Vitest. No animation, icon, UI-kit or date libraries.
   Icons, if any, are small inline SVGs with `aria-hidden="true"`. Part B (Akshay) is Python 3.11 standard library
   only, like the rest of `services/instagram_backend`.
3. **Read `apps/creator-workspace/AGENTS.md` first.** This Next.js version differs from older training data; check
   `node_modules/next/dist/docs/` before using any Next.js API.
4. **Reads go straight to Supabase with RLS. Every write goes through the send API** (BASELINE 2.3). The browser never
   writes to Supabase and never sees the service-role key.
5. **No AI text reaches a follower without the creator's approval** (BASELINE rule 9). The UI gate in section 7 is
   for usability; Part B enforces the same gate on the server.
6. **Never log DM text, draft text, answer text, tags or citations.** Log error codes and ids only, as
   `lib/inbox/queries.ts` already does.
7. **Reuse before you write.** `labels.ts`, `LocalTime`, `PageHeader`, `PageSection`, `Placeholder`, `RefreshButton`,
   `RealtimeRefresh`, `QueueTabs`, the reply-box pattern and the `pdm-*` colour tokens already exist. Keep the same look.
8. **Every new pure function gets a Vitest test** (same style as `thread.test.ts`, `reply.test.ts`).
9. Use the status and type names exactly as written here. They come from `packages/contracts/src/index.ts`.
10. When anything is unclear, **stop and ask Karthik**. Do not guess.

---

## 1. Start here (Ritvik)

```bash
git checkout main
git pull origin main
git checkout -b feature/creator-inbox-answers
pnpm install
cp apps/creator-workspace/.env.example apps/creator-workspace/.env.local   # if you don't have it yet
pnpm --filter @professordm/creator-workspace dev                           # http://localhost:3001
```

`.env.local` needs the same three values as before: `NEXT_PUBLIC_SUPABASE_URL`,
`NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`, `INSTAGRAM_SEND_API_URL` (ask Karthik if you don't have them). **No new
environment variables.** Sign in with the staging creator account.

Checks before every push (same as CI):

```bash
pnpm --filter @professordm/creator-workspace lint
pnpm --filter @professordm/creator-workspace typecheck
pnpm --filter @professordm/creator-workspace test
pnpm --filter @professordm/creator-workspace build
```

**Order of work:** Akshay builds Part B at the same time as you build Part C. The API contract in section 4 is fixed,
so you don't wait for him: build the UI against the real staging data that already exists (section 2.3) and test
`approveAnswer` with mocks. The Send button works on staging once Akshay has deployed Part B.

---

## 2. What exists today (do not rebuild)

### 2.1 Your milestone-1 work (keep it)

| Piece | File | Keep as |
|---|---|---|
| Sign-in, role gate, shell, sidebar + mobile nav | `app/login`, `app/(workspace)/layout.tsx`, `workspace-nav.tsx` | unchanged |
| All Instagram DMs with AI labels | `/incoming` page, `MessageRow`, `listInboundMessages` | unchanged (this is diagram Flow 1) |
| Conversation with one sender + manual reply | `/inbox/[id]`, `getThread`, `buildThread`, `ReplyBox`, `sendReply` | unchanged, linked from the question page |
| Labels from contracts | `lib/inbox/labels.ts` | extend (section 3) |
| Live updates | `RealtimeRefresh` | extend with two tables |

### 2.2 What the AI pipeline now writes (PR #23)

For every Instagram DM the worker classifies, and for an expert question it creates:

| Table | Row | Fields you show |
|---|---|---|
| `inbound_messages` | the DM | `text`, `received_at`, `category`, `confidence`, `status`, `reason` |
| `clarification_rounds` | AI clarification + the follower's reply | `round`, `prompt`, `reply` |
| `questions` | the paid question (payment stubbed) | `id`, `status`, `question_text`, `safety_flagged`, `paid_at`, `follower_id`, `origin_message_id`, `source` |
| `drafts` | the AI draft (one per question) | `status` (`ready` / `no_draft`), `ai_text`, `citations`, `knowledge_coverage` (`high`/`partial`/`none`), `missing_info` (list of short phrases), `reason` (`no_coverage`, `invalid_output`, `safety_blocked`, `empty_question`), `final_text`, `approved_at` |
| `safety_flags` | flags on the DM (checkpoint 1) or draft (checkpoint 2) | `target_type`, `checkpoint`, `layer`, `category`, `detail`, `status` |

`citations` is a JSON list: `[{"kind":"knowledge","ref":"<entry id>","title":"Guide > Section > Subsection","hpa_id":"HPA-...","supports":"what this source backs up"}]`.
The draft text itself contains **no** citation markers.

Question status while it is in the Creator Workspace:

| `questions.status` | Meaning |
|---|---|
| `paid`, `drafting` | AI is writing the draft (usually under 20 s) |
| `awaiting_creator` | Kristin's turn. With a `drafts` row (`ready` or `no_draft`), or **no row** = AI was unavailable after 3 tries |
| `approved`, `delivering` | Send in progress (Part B) |
| `delivered` | Answer DM sent (Part B) |

### 2.3 Real staging data to build against

Already on staging from the Nov 2 tests: one question with a `ready` draft (calathea, coverage `partial`, 8 passages),
one from a clarification flow (pothos, reassessed), and two questions in `awaiting_creator` with **no drafts row**
(AI unavailable). `/incoming` also shows a `creator_decision` / `safety_concern` message. That covers every card state
in section 6 except "flagged question"; scenario 6 in section 10 creates one.

---

## 3. Files

### Part C: Ritvik (`apps/creator-workspace/`)

**Create**

| File | Purpose |
|---|---|
| `src/lib/inbox/questions.ts` | `server-only` reads: `listQuestions(queue)`, `getQuestion(id)`, `queueCounts()`, `listOpenFlags()`, `listDecisionMessages()` (section 5) |
| `src/lib/inbox/question-state.ts` | Pure: `cardState(question, draft, lastSend)` → label, tone, action (section 6). No Supabase |
| `src/lib/inbox/question-state.test.ts` | Every state in section 6 |
| `src/lib/inbox/answer.ts` | Pure: `normalizeAnswer`, `changeRatio(aiText, text)`, `parseTags(input)`, `checkSendGate(...)`, `parseAnswer(formFields)` (section 7) |
| `src/lib/inbox/answer.test.ts` | Gate, tags, byte limit, change ratio |
| `src/lib/inbox/send-api.ts` | `server-only`: `postToSendApi(body)`, the fetch + session + error mapping now inside `sendReply`, shared by both actions |
| `src/components/inbox/question-card.tsx` | One queue card (section 8.1) |
| `src/components/inbox/status-chip.tsx` | Shared chip: label + tone + optional pulse dot |
| `src/components/inbox/answer-composer.tsx` | `"use client"`: editor, gate, tags, flag acknowledgement, confirm dialog (section 8.3) |
| `src/components/inbox/source-list.tsx` | Citations, coverage badge, "what the guides don't cover" |
| `src/components/inbox/flag-panel.tsx` | Safety flags with plain-language descriptions |
| `src/app/(workspace)/inbox/question/[id]/page.tsx` | The answer workspace (section 8.2) |

**Change**

| File | Change |
|---|---|
| `src/app/(workspace)/inbox/page.tsx` | List **questions** waiting for Kristin (not raw DMs). Link "All messages" to `/incoming` |
| `src/app/(workspace)/sent/page.tsx` | List `delivered` questions with the sent answer and time |
| `src/app/(workspace)/moderation/page.tsx` | Fill "Flagged questions" (open flags) and add "Needs your decision" (`creator_decision` DMs). Leave the other placeholders |
| `src/components/queue-tabs.tsx` | Show counts: `Inbox 3`, `Sent 5`, `Moderation 1` |
| `src/components/inbox/realtime-refresh.tsx` | Also listen to `questions` and `drafts` |
| `src/lib/inbox/actions.ts` | Add `approveAnswer` server action; `sendReply` now calls `postToSendApi` (same behaviour, existing tests stay green) |
| `src/lib/inbox/labels.ts` | Add `QUESTION_STATUS_LABELS`, `COVERAGE_LABELS`, `NO_DRAFT_REASON_LABELS`, `FLAG_LABELS` |
| `src/lib/inbox/actions.test.ts` | Add `approveAnswer` cases (section 9) |
| `src/app/globals.css` | Only if needed: `--color-pdm-success`, `--color-pdm-danger`, one `@keyframes` for the drafting shimmer, and a `prefers-reduced-motion` rule |
| `apps/creator-workspace/README.md` | Routes table + "Answering questions" section |

### Part A: Karthik (`supabase/migrations/20261102_011_creator_inbox_policies.sql`)

1. `safety_flags`: enable RLS; **select** policy for the creator: flag on a message whose follower belongs to
   `current_creator_id()`, or on a draft whose question belongs to it; admins read all.
2. `tags`, `question_tags`: **select** policies for the creator's own rows; admins read all.
3. Realtime: `alter publication supabase_realtime add table public.questions, public.drafts` (guarded like 006).
4. Select only. No insert/update policies: writes go through the send API with the service role.

### Part B: Akshay (`services/instagram_backend/`)

Extend `POST /api/send` (section 4). Files: `sender.py`, `clients.py` (new repository methods), `tests/test_sender.py`.
Branch `feature/send-api-question-answers`, own PR. Deploy the existing `professordm-staging-oct16-send` stack; the
change set must show only the send function's code and is sent to Karthik before it is executed. Ritvik does not
change any file in `services/`.

---

## 4. Part B: the send API learns to answer a question

Same endpoint, same auth, same response shape (`{id, status, meta_message_id}`). Today's manual reply keeps working
unchanged when `question_id` is absent.

**New optional body fields**

| Field | Rule |
|---|---|
| `question_id` | UUID. When present, the request answers this question |
| `tags` | 1 to 5 strings, each trimmed, lower-cased, 1 to 40 characters. **Required** with `question_id` |
| `reviewed_flag_ids` | UUID list. Must contain **every** open flag of the question (see step 4) |

`inbound_message_id` must equal the question's `origin_message_id` (else 400). `text` keeps today's rules
(non-empty, at most 999 characters and 1000 UTF-8 bytes).

**Steps when `question_id` is present** (after today's auth and ownership checks):

1. **Idempotency first.** If an outbound row already exists for `client_request_id`, return it as today (a double
   click never sends twice).
2. **Load** the question (`id, creator_id, status, origin_message_id, follower_id, source`). Missing or another
   creator's: 404. `source` must be `instagram`. `status` must be `awaiting_creator`, else **409** `{"error":"not_awaiting_answer"}`.
3. **Load** its drafts row (may not exist).
4. **Server gate** (the same rules as the UI, section 7):
   - `tags` has 1 to 5 valid entries, else **422** `{"error":"tags_required"}`.
   - If the draft has `ai_text`: `normalize(text) != normalize(ai_text)` (collapse whitespace, trim), else **422**
     `{"error":"edit_required"}`.
   - Open flags = `safety_flags` with `status='open'` and (`target_type='message'` and `target_id=origin_message_id`)
     or (`target_type='draft'` and `target_id=<draft id>`). Every one must be in `reviewed_flag_ids`, else **422**
     `{"error":"flags_unreviewed"}`.
5. **Claim:** `PATCH questions?id=eq.{q}&status=eq.awaiting_creator → {"status":"approved"}`. No row back: 409.
6. **Save the answer:** drafts row exists → `PATCH` `final_text`, `edit_distance` (character Levenshtein against
   `ai_text`, null when there was no AI text), `status='approved'`, `approved_at=now()`. No row → insert one with
   `ai_text=null`, `citations='[]'`, `final_text`, `status='approved'`, `approved_at=now()`.
7. **Flags:** `PATCH` the reviewed flags → `status='creator_reviewed'`, `reviewed_by=<user id>`.
8. **Tags:** for each name, find `tags (creator_id, name)` or insert it; insert `question_tags` (ignore duplicates).
9. **Audit:** one `audit_log` row: `actor_id=<user id>`, `action='answer.approved'`, `entity='question'`,
   `entity_id=<question id>`, `before_after={"edit_distance": n, "tag_count": k, "had_ai_draft": bool, "flags_reviewed": m}`.
   **No text.**
10. **Send:** reserve the outbound row exactly as today but with `draft_id=<draft id>` (type `answer`), set the
    question to `delivering`, then call Meta once.
    - **Sent:** outbound `sent` + `meta_message_id`; question → `delivered`, `delivered_at=now()`,
      `hold_ends_at=now()+3 days`.
    - **Meta failed:** outbound `failed`; question → `awaiting_creator` (the draft keeps her `final_text`, so nothing
      she wrote is lost). Return 502 `{"error":"delivery_failed"}`.

**Tests (`test_sender.py`):** manual reply unchanged; answer with edit + tag → delivered, draft approved,
`edit_distance` set, audit row without text; unchanged text → 422 `edit_required`; no tags → 422; unreviewed flag →
422; no drafts row → inserted, no edit check; question not `awaiting_creator` → 409; double request → one Meta call;
Meta failure → question back to `awaiting_creator`, outbound `failed`; other creator's question → 404.

**Out of scope here (later phases):** checkpoint-3 final screen by the AI worker, follow-ups, decline + refund, the
Q+A embedding job (Chinmay), real Stripe.

---

## 5. Part C: data reads (`lib/inbox/questions.ts`)

All reads use the signed-in user's Supabase client (RLS). Log only `error.code`.

| Function | Query |
|---|---|
| `listQuestions("inbox")` | `questions` where `status in (paid, drafting, awaiting_creator, approved, delivering)`, with `follower:ig_followers(id, username)`, `drafts(id, status, knowledge_coverage, reason, final_text)`, ordered **oldest `paid_at` first** (fair queue: whoever waited longest is on top). Flagged questions sort first |
| `listQuestions("sent")` | `status in (delivered, accepted, closed)`, newest `delivered_at` first, with the draft `final_text` |
| `getQuestion(id)` | UUID check (reuse the pattern in `queries.ts`), then the question + follower + drafts row (all fields in 2.2), the origin `inbound_messages` row (`text, received_at, category, confidence, reason`), its `clarification_rounds`, the open and reviewed `safety_flags` for the origin message and the draft, and the newest `outbound_messages` row for the draft (`status, created_at`). Not found or another creator's: `notFound()` |
| `queueCounts()` | three `count: "exact", head: true` queries: inbox statuses above; sent statuses; Moderation = open flags + `creator_decision` messages |
| `listOpenFlags()` | `safety_flags` with `status='open'`, joined in code to their question (via origin message or draft) |
| `listDecisionMessages()` | `inbound_messages` where `status='creator_decision'`, newest first, with follower |

`reason` on `inbound_messages` is the AI's classification note. It is fine to **show** it to the creator; it must
never be **logged**.

---

## 6. Card states (`question-state.ts`)

`cardState` returns `{ label, tone, hint, action }`. The tone picks the chip colour. Test every row.

| Condition (first match wins) | Label | Tone | Hint under the title | Action button |
|---|---|---|---|---|
| status `paid` or `drafting` | AI is drafting | `progress` (pulsing dot) | "Usually ready in under 20 seconds." | none (card not clickable yet) |
| status `approved` or `delivering` | Sending | `progress` | "Delivering to Instagram…" | View |
| has open flags | Review flag first | `danger` | "A safety check flagged this. Review it before answering." | Review |
| last send `failed` | Send failed | `danger` | "Your answer was saved. Open it to try again." | Try again |
| draft `ready` | Draft ready | `accent` | coverage line, e.g. "Partly covered by your guides" | Review & answer |
| draft `no_draft` | Answer by hand | `neutral` | reason line, e.g. "Your guides don't cover this yet" | Answer |
| no drafts row | AI unavailable | `neutral` | "The AI couldn't draft this. Answer it yourself." | Answer |

Plain-language labels (put them in `labels.ts`):

| Value | Shown as |
|---|---|
| coverage `high` / `partial` / `none` | "Well covered by your guides" / "Partly covered by your guides" / "Not in your guides" |
| reason `no_coverage` | "Your guides don't cover this yet" |
| reason `invalid_output` | "The AI draft didn't pass its quality checks" |
| reason `safety_blocked` | "The AI held back a draft for safety" |
| reason `empty_question` | "The question had no text" |
| flag `layer`/`category` | moderation `harassment` → "Harassing language", policy `safety_concern` → "Safety concern", policy `risk_topic` → "Sensitive topic: {detail}", anything else → "Flagged: {category}" |

---

## 7. The send gate (`answer.ts`, mirrored by Part B)

| Rule | Why | UI behaviour |
|---|---|---|
| Text not empty, ≤ 999 characters and ≤ 1000 UTF-8 bytes | Instagram's limit | live counter "812 / 1000"; amber at 900, red over 1000 |
| If there was an AI draft: text differs from it after `normalizeAnswer` | "You are the expert. Make this answer yours." (diagram 05) | Send stays disabled with that sentence until she edits |
| 1 to 5 tags, each 1 to 40 characters, lower-case | Feeds the Knowledge Database later | chip input; Enter or comma adds a tag |
| Every open flag acknowledged | Moderation path (Nov 13) | checkbox per flag: "I've reviewed this" |

`changeRatio(aiText, text)` = share of words that differ (word-level diff, 0 to 1). It drives the "Your voice"
meter (section 8.3) and is **not** a gate threshold: one real edit is enough.

`parseAnswer` validates the form fields like `parseReply` does and returns typed errors the UI can show.

---

## 8. Screens

Visual language: keep the current Creator Workspace look (amber `pdm-accent`, stone neutrals, white surfaces,
`rounded-lg` borders, system font). Use the existing tokens; do not introduce a second accent colour. Cards use a
border, not a shadow; only the confirm dialog is elevated.

### 8.1 Inbox (`/inbox`)

```
Inbox                                                        [Refresh]
Questions waiting for your answer, oldest first.     All messages ->
[ Inbox 3 ]  Sent 5   Moderation 1
------------------------------------------------------------------------
| @plantlover22                         waiting 2 h        Draft ready |
| My calathea's leaf tips are going brown and crispy. It's by a        |
| north window and I water it every week.                              |
| Partly covered by your guides · 3 sources · Instagram · Paid (test)  |
|                                                    [Review & answer] |
------------------------------------------------------------------------
| @monstera.mom                         waiting 5 min  Review flag first|
| Is my monstera safe for my cat to chew on?                           |
| A safety check flagged this. Review it before answering.  [Review]  |
------------------------------------------------------------------------
| @newgrower                            just now     * AI is drafting   |
| [shimmer line] [shimmer line]                                        |
------------------------------------------------------------------------
```

- Header line: username (or "Unknown sender"), relative wait time (`LocalTime` gives the exact time on hover), chip.
- Body: the question text, 2 lines max. Footer: hint from section 6, source count, `Instagram`, `Paid (test)` while
  payment is stubbed (`price_cents` is null).
- Whole card is one link (like `MessageRow`), with the action as visible text, not a nested button.
- **Empty state:** "You're all caught up. New questions appear here as soon as the AI has drafted them." plus a link
  to `/incoming`.
- **Loading:** `loading.tsx` with three skeleton cards of the same height (no spinner).
- **Error:** the existing red alert pattern with "Couldn't load questions. Try again."
- New questions appear without a refresh (Realtime on `questions` and `drafts`).

### 8.2 Answer workspace (`/inbox/question/[id]`)

Two columns on `lg` and wider (`grid lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] gap-6`), one column below `lg`
in this order: question, flags, composer, sources, conversation.

**Left column: context**
1. Back link "Back to inbox", username, "View full conversation" → `/inbox/{follower_id}`.
2. **The question**: the follower's original DM, received time, category chip + "95% confident", and the AI's
   classification note (`reason`) in muted text under a "Why the AI sorted it this way" disclosure (`<details>`).
3. **Clarification** (if any): the AI's question and the follower's reply as two small bubbles, reusing `Bubble`
   styling from the conversation page.
4. **Flag panel** (if any): one row per flag in plain language (section 6), checkpoint as "On the message" / "On the
   AI draft", and the acknowledgement checkbox. Reviewed flags show "Reviewed by you".

**Right column: the answer**
5. **Composer** (section 8.3).
6. **Sources**: coverage badge; each citation as a row with the guide title (split on `>` into a breadcrumb, last
   part bold) and its `supports` sentence; "What your guides don't cover" list from `missing_info` when present,
   phrased as a prompt to add that knowledge herself.

### 8.3 Composer (`answer-composer.tsx`)

- Textarea pre-filled with, in order: her saved `final_text` (after a failed send) → `ai_text` → empty. Label:
  "Your answer to @username". `rows` grows with content (CSS `field-sizing: content` with a `min-h`).
- Above the textarea, a one-line status: "AI draft · edit it into your own words" / "No AI draft · write your
  answer" / "Your last version · it wasn't delivered".
- **Your voice meter** (only with an AI draft): a thin bar + text "You changed 18% of the draft". At 0%: "Not
  edited yet". `aria-live="polite"`, updated on input (debounced 300 ms).
- **Reset to AI draft** (text button, only when edited): restores `ai_text`, with an "Undo" link for 10 s.
- **Tags**: chip input with label "Tags (1 to 5)". Helper: "Tags help you find this answer later." Remove a chip with
  its × button or Backspace in an empty input.
- **Byte counter** bottom-right.
- **Send gate message** (`aria-live`): lists only what is still missing, e.g. "Edit the draft so it's in your words ·
  Add at least one tag". Send is disabled until the list is empty.
- **Send flow:** "Review & send" opens a native `<dialog>` confirm showing exactly what will be sent, the recipient,
  and "This sends a DM on Instagram now." Buttons: "Send answer" (primary) and "Keep editing". `Esc` closes it.
  `Ctrl/Cmd + Enter` in the textarea opens it when the gate passes.
- **While sending:** button "Sending…", textarea read-only, chip "Sending".
- **After success:** green confirmation "Answer sent to @username on Instagram" with "Next question →" (the next
  card in the Inbox) and "Back to inbox". Focus moves to that confirmation.
- **Errors** map Part B responses to plain sentences: `edit_required` → "Edit the draft so it's in your words
  before sending." · `tags_required` → "Add at least one tag." · `flags_unreviewed` → "Review the safety flags
  first." · `not_awaiting_answer` → "This question was already answered. Refresh to see it." · `delivery_failed` →
  "Instagram didn't accept the message. Your answer is saved. Try again in a minute." · 401 → existing session
  message. Text she typed is never cleared on error.
- **Unsaved changes:** a `beforeunload` warning while the text differs from what was loaded and not yet sent.
- One `client_request_id` per send press, regenerated only after success (same pattern as `ReplyBox`).

### 8.4 Sent (`/sent`)

Cards with username, question (1 line), her answer (2 lines), "Sent {time}", edit meter value ("Your edits: 34%"),
tags. Empty state: "Answers you send appear here."

### 8.5 Moderation (`/moderation`)

- **Flagged questions**: one row per question with open flags, flag labels, link "Review" → the answer workspace.
- **Needs your decision** (new section): `creator_decision` DMs (for example `safety_concern`), each with the label,
  the AI's note and a link to the conversation (`/inbox/{follower_id}`), where she can reply manually or ignore it.
- Keep the other placeholders.

### 8.6 Usability checklist (Nielsen's 10 heuristics, all required)

| # | Heuristic | Where this spec meets it |
|---|---|---|
| 1 | Visibility of system status | Card chips for every state, drafting pulse, Sending chip, live updates, counts on tabs |
| 2 | Match with the real world | Plain labels ("Partly covered by your guides", "Answer by hand"), no internal codes, wait time in human units |
| 3 | User control and freedom | Reset to AI draft + Undo, Keep editing in the dialog, Esc closes, back links, nothing auto-sends |
| 4 | Consistency and standards | Same chips, buttons, alerts and bubbles as milestone 1; labels from contracts; one accent colour |
| 5 | Error prevention | Send gate, byte counter, confirm dialog with the exact text, one request id per press, unsaved-changes warning |
| 6 | Recognition rather than recall | Original DM, clarification, flags and sources on the same screen as the editor; missing-info list |
| 7 | Flexibility and efficiency | Ctrl/Cmd+Enter, Enter/comma for tags, "Next question" after sending, oldest-first queue |
| 8 | Aesthetic and minimalist design | One primary action per screen, classification note behind a disclosure, sources compact |
| 9 | Recognise, diagnose, recover from errors | Specific messages per error, text kept on failure, "Send failed · Try again" card state |
| 10 | Help and documentation | Helper text on gate, tags and empty states; hints on every card |

### 8.7 Accessibility (WCAG 2.2 AA)

Keyboard-only use of every action; visible focus (already global); targets at least 44 × 44 px (`min-h-11`);
colour is never the only signal (chips have text); `aria-live` for the meter, gate and send status; the dialog traps
focus and returns it to the trigger; `prefers-reduced-motion` stops the pulse and shimmer; contrast at least 4.5:1;
layout works at 390 px wide with no horizontal scroll.

---

## 9. Tests (Part C)

`question-state.test.ts`: every row of section 6, including "flag beats draft ready" and "failed send beats draft".
`answer.test.ts`: `normalizeAnswer` (spaces, line breaks), `changeRatio` (0 for identical, 1 for all new, a middle
case), `parseTags` (trim, lower-case, dedupe, max 5, max 40), gate (each rule alone, all passing, no-draft case skips
the edit rule), byte limit with emoji and accented text.
`actions.test.ts`: `approveAnswer` posts `question_id`, `tags`, `reviewed_flag_ids` with the session token; maps
422/409/502/401 to the sentences in 8.3; `sendReply` tests unchanged and passing.
No test calls real Supabase, the send API or Instagram.

---

## 10. Staging acceptance (all must pass before the PR is approved)

Part A applied and Part B deployed first. Run against the Vercel preview of the branch, signed in as the staging
creator. Use test Instagram accounts only.

| # | Do | Expected |
|---|---|---|
| 1 | Open `/inbox` | Calathea question shows "Draft ready", coverage, source count, wait time; the two AI-unavailable questions show "AI unavailable" |
| 2 | Open it, press Send without editing | Send disabled; gate says to edit and add a tag |
| 3 | Edit one sentence, add tag `calathea`, send | Confirm dialog shows the exact text; the DM arrives on the test account; card moves to Sent; `questions.status='delivered'`; draft `approved` with `edit_distance`; one `audit_log` row |
| 4 | Double-click Send in the dialog | Exactly one DM |
| 5 | Answer an "AI unavailable" question by hand with a tag | Sent without the edit rule |
| 6 | From a fresh account DM "Is my monstera safe for my cat to chew on?" | Card appears live as "AI is drafting", then a flagged or no-draft state; if flagged, it is listed in Moderation and Send stays locked until the flag is acknowledged |
| 7 | Keep `/inbox` open and DM a new question from a fresh account | Card appears without refresh within about 20 s |
| 8 | Phone width (390 px) and keyboard only | Every action reachable; no horizontal scroll |

---

## 11. PR

- **Part A** (Karthik): PR #24, already applied to staging.
- **Part B** (Akshay): `feature/send-api-question-answers`, own PR, deployed before the acceptance run.
- **Part C** (Ritvik): `feature/creator-inbox-answers`, one PR. Commits in small steps (data layer + tests → card
  states → Inbox → answer workspace → composer → Sent and Moderation → README). Commit this spec in the same PR.
- PR description: what changed, screenshots (desktop + 390 px), test counts, acceptance results 1 to 8, and
  "No answer text in logs (checked)".
- Reviewers: Karthik (everything), Akshay (`services/instagram_backend/` and `send-api.ts`).

---

## 12. Prompt for Ritvik's coding agent

> Read `docs/plans/creator-inbox-spec.md` fully, then `apps/creator-workspace/AGENTS.md`, `README.md` and the files in
> `src/lib/inbox/`. Implement **Part C only** (Part A is applied, Part B is Akshay's), following section 0 exactly.
> Work on branch `feature/creator-inbox-answers` from the latest `main`. Section 4 is the API contract you call;
> do not change any file in `services/`. Build in this order: section 5 reads, section 6 states with tests, section 7
> gate with tests, the Inbox page, the answer workspace, the composer, Sent, Moderation, README. Run lint, typecheck,
> test and build after each step. Do not add dependencies, do not touch files outside section 3, and never log
> message, draft or answer text. If anything in the spec is unclear or seems wrong, stop and ask.
>
> **Akshay's agent (Part B):** read sections 0, 4 and 11 and `services/instagram_backend/sender.py`, `clients.py` and
> their tests. Implement section 4 only on branch `feature/send-api-question-answers`, with the listed tests, Python
> 3.11 standard library only. Do not deploy: send the change set to Karthik first.
