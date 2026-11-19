# Creator Workspace

Next.js app where the creator (Sweetlife Flora) and ProfessorDM admins review questions, answer them, moderate and track earnings. Owner: Ritvik. Flows: `docs/architecture/05-ritvik-creator-transactions.mmd`.

Same stack as `apps/consumer`: Next.js 16, React 19, Tailwind v4, `@supabase/ssr`.

## Run it

```sh
cp apps/creator-workspace/.env.example apps/creator-workspace/.env.local   # fill in the values
pnpm install
pnpm --filter @professordm/creator-workspace dev                           # http://localhost:3001
```

| Variable | Value |
|---|---|
| `NEXT_PUBLIC_SUPABASE_URL` | Supabase project URL (same project as `apps/consumer`) |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | Supabase publishable key |
| `INSTAGRAM_SEND_API_URL` | Server-side staging `POST /api/send` URL from the SAM `SendUrl` output |

Checks (same as CI): `pnpm --filter @professordm/creator-workspace lint`, `typecheck`, `test`, `build`. Unit tests use Vitest (`src/**/*.test.ts`).

## Who can sign in

Only `profiles.role` = `creator` or `admin`. A `consumer` who signs in is signed out with "This account doesn't have access to the Creator Workspace." There is no public sign-up in V1; accounts are invite-only.

- `src/proxy.ts` refreshes the session and sends signed-out users to `/login?next=…`. It does not check roles.
- `src/lib/auth/actions.ts` `signIn` checks the role right after the password.
- `src/app/(workspace)/layout.tsx` checks the role on every signed-in page and sends anyone else to `/auth/forbidden`, which signs them out.


## Routes

| Route | Page | Status |
|---|---|---|
| `/login` | Sign in | Done |
| `/` | ProfessorDM Bank (home) | Placeholder |
| `/incoming` | All inbound Instagram messages, one row per question with its clarification replies folded in (matched on `clarification_rounds.reply`, like the conversation page), latest activity first | Done (Oct 16; grouped in SCRUM-144) |
| `/inbox` | Questions waiting for the creator, oldest first, with card states and live updates | Done (creator inbox) |
| `/inbox/question/[id]` | Answer workspace: question, clarification, flags, sources and the composer | Done (creator inbox) |
| `/inbox/[id]` | Conversation with one sender (`id` = `ig_followers.id`), manual reply | Done (SCRUM-56, SCRUM-73) |
| `/sent` | Delivered answers with edit share and tags | Done (creator inbox) |
| `/moderation` | Flagged questions and DMs that need the creator's decision; other sections placeholders | Partly done (creator inbox) |
| `/knowledge` | Knowledge Database: saved answers (`source = 'question'`) with Publish / Make private; Add a fact is a placeholder | Partly done (SCRUM-143) |
| `/profile` | Creator settings | Placeholder |

Reads go straight to Supabase with RLS; every write goes through the `api` service (BASELINE.md section 2.3).

## Inbox data

Code: `src/lib/inbox/` (`queries.ts` reads, `thread.ts` merges a conversation, `labels.ts` readable names from `@professordm/contracts`).

| Shown | Comes from |
|---|---|
| Message list | `inbound_messages` + sender `username` from `ig_followers` |
| Category | `override_category` if the creator changed it, else `category` |
| Clarification question + reply | `clarification_rounds.prompt` / `reply` |
| Answers sent back (AI draft) | `questions` (by sender) → `drafts.final_text` + `approved_at` → `outbound_messages.type` + `status` |
| Replies the creator typed | `outbound_messages` where `follower_id` = sender and `draft_id` is null → `text`, `created_at`, `status` |

`ig_followers` holds everyone who has DMed the creator, not only people who follow them.

**Requires migrations** `supabase/migrations/20261011000003_creator_read_policies.sql`, `20261011000004_creator_thread_policies.sql` (select-only RLS: a creator reads their own contacts' data, admins read all), `20261012000005_creator_direct_answer_outbound.sql` (reply columns + insert policy), and `20261014000006_oct16_realtime_publication.sql` (live inbound/outbound updates).

## Replying (SCRUM-73)

The conversation page has a reply box (`components/inbox/reply-box.tsx`). Send calls the `sendReply` server action (`lib/inbox/actions.ts`), which sends the creator session token to the staging `POST /api/send` Lambda. The Lambda validates ownership, reserves one `outbound_messages` row with `type = 'answer'`, `draft_id = null`, `status = 'pending'`, and sends the manual text through Meta. Realtime refreshes the conversation when the status changes.

- Empty or whitespace-only replies are blocked in the form, the action (`lib/inbox/reply.ts`) and a database check.
- Double clicks: each Send press carries a `client_request_id` (unique in the database). A repeat returns the existing delivery state without another Meta send.
- This is the manual reply. AI-drafted answers to questions go through the answer workspace (below).
- The backend-only Vault RPC in migration `20261014000007_meta_page_token_rpc.sql` resolves the linked page token. The browser never receives the token or Supabase service-role key.

**Known limitation:** only typed replies use the new `follower_id`, `text` and `created_at` columns. Other sends without a draft (Ask link, confirmation, status) still don't fill them, so they can't be shown in a conversation, and AI-drafted answers are placed at `drafts.approved_at`, not the actual send time.

## Answering questions (creator inbox)

Spec: `docs/plans/creator-inbox-spec.md` (Part C). After the AI pipeline drafts an answer, the creator reviews it, makes it her own and sends it as an Instagram DM.

1. `/inbox` lists `questions` in `paid`, `drafting`, `awaiting_creator`, `approved` and `delivering`, oldest `paid_at` first, flagged questions on top. `lib/inbox/question-state.ts` picks each card's label and action (AI is drafting, Sending, Review flag first, Send failed, Draft ready, Answer by hand, AI unavailable).
2. `/inbox/question/[id]` shows the original DM, the AI's classification note, clarification rounds, safety flags and the guide sources next to the composer (`components/inbox/answer-composer.tsx`).
3. The send gate (`lib/inbox/answer.ts`) keeps Send disabled until the answer is 1 to 999 characters and at most 1000 UTF-8 bytes, differs from the AI draft after whitespace is normalised (when there was a draft), has 1 to 5 tags of up to 40 characters, and every open flag is ticked "I've reviewed this". A confirm dialog shows the exact text before anything is sent.
4. The `approveAnswer` server action (`lib/inbox/actions.ts`) posts `question_id`, `tags` and `reviewed_flag_ids` with the creator's session token through `lib/inbox/send-api.ts`, shared with `sendReply`. The send API checks the same gate again, saves the answer, tags and audit row, and delivers the DM. The question then moves to `/sent`.

| Shown | Comes from |
|---|---|
| Queue cards | `questions` + `ig_followers` + `drafts` (coverage, reason, citation count) + newest `outbound_messages.status` + open `safety_flags` |
| Answer workspace | the above + origin `inbound_messages` (`text`, `category`, `confidence`, `reason`) + `clarification_rounds` + `drafts.citations` and `missing_info` |
| Sent | `drafts.final_text` and `ai_text` (edit share), `question_tags` → `tags.name` |
| Moderation | open `safety_flags` joined to their question; `inbound_messages` with `status = 'creator_decision'` |
| Tab counts | `lib/inbox/questions.ts` `queueCounts()`: Inbox and Sent are `count: "exact"` queries on question status; Moderation = flagged questions (`listOpenFlags()`) + `creator_decision` DMs with a follower, the same rows the Moderation page lists |

**Request ids.** Each send press carries a `client_request_id`. The action returns the id for the next press (`nextRequestId`): a new one after any answer that proves nothing is in flight (success, any 4xx, 502 `delivery_failed`), the same one when the outcome is unknown (network error, timeout, other 5xx, `pending`), so a retry can never send a second DM.

**Requires** migration `supabase/migrations/20261102000011_creator_inbox_policies.sql` (select policies on `safety_flags`, `tags`, `question_tags`; Realtime on `questions` and `drafts`) and the send API extension (spec Part B) deployed. Without Part B, Send returns an error and the creator's text stays in the composer.

**Not logged:** DM, draft and answer text, tags and citations. Reads log the Supabase error code only.

**Known gaps:** the Inbox also lists Knowledge-app questions, which the send API doesn't answer yet (the composer says so).

## Deciding on DMs in Moderation (SCRUM-140)

Each DM in "Needs your decision" has **I replied** and **No reply needed**. Either one calls the `decideMessage` server action, which calls the database function `record_message_decision` (migration `supabase/migrations/20261117000012_message_decisions.sql`) with the creator's session. In one transaction it checks the DM is hers (or the caller is an admin), moves it from `creator_decision` to `closed_no_action`, marks its open message flags `creator_reviewed`, and writes an `audit_log` row (`action = 'message.decided'`, the decision and flag count, no DM text). A DM already decided (double click, second tab) is left as is. The row leaves the list and the Moderation count drops. Turning a DM into a paid question is not part of this. Spec: `docs/plans/scrum-140-moderation-decisions-spec.md`.

**Requires** migration 012 run in the Supabase SQL editor. Without it, the buttons show "Couldn't save your decision. Try again."

## Publishing answers (SCRUM-143)

`/knowledge` lists the creator's saved answers: `knowledge_entries` with `source = 'question'`, read through the RLS policy from migration 008. They are newest delivered first, then entries without a question by title. **Publish** / **Make private** calls the `setEntryPublished` server action, which calls the database function `set_knowledge_entry_published` (migration `supabase/migrations/20261119000014_publish_knowledge_entries.sql`) with the creator's session. In one transaction it checks the entry is her answer entry (or the caller is an admin), sets `published` and writes an `audit_log` row (`knowledge.published` / `knowledge.unpublished`, no answer text). The consumer Knowledge app shows only published entries. Rows are created by the AI worker's store job after delivery (private by default), so they appear here with no change. Spec: `docs/plans/scrum-143-publish-answers-spec.md`.

**Requires** migration 014 run in the Supabase SQL editor. Without it, the button shows "Couldn't save. Try again."
