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
| `/incoming` | Incoming Messages (AI labels, override) | Placeholder |
| `/inbox` | Incoming Instagram messages, newest first (read only) | Done (SCRUM-56) |
| `/inbox/[id]` | Conversation with one sender (`id` = `ig_followers.id`) | Done (SCRUM-56) |
| `/sent` | Sent answers, follow-ups, ratings | Placeholder |
| `/moderation` | Flagged items; extra admin review section | Placeholder |
| `/knowledge` | Knowledge Database | Placeholder |
| `/profile` | Creator settings | Placeholder |

Reads go straight to Supabase with RLS; every write goes through the `api` service (BASELINE.md section 2.3).

## Inbox data

Code: `src/lib/inbox/` (`queries.ts` reads, `thread.ts` merges a conversation, `labels.ts` readable names from `@professordm/contracts`).

| Shown | Comes from |
|---|---|
| Message list | `inbound_messages` + sender `username` from `ig_followers` |
| Category | `override_category` if the creator changed it, else `category` |
| Clarification question + reply | `clarification_rounds.prompt` / `reply` |
| Answers sent back | `questions` (by sender) → `drafts.final_text` + `approved_at` → `outbound_messages.type` + `status` |

`ig_followers` holds everyone who has DMed the creator, not only people who follow them.

**Requires migrations** `supabase/migrations/20261011_003_creator_read_policies.sql` and `..._004_creator_thread_policies.sql` (select-only RLS: a creator reads their own contacts' data, admins read all). Without them the inbox is empty.

**Known limitation:** `outbound_messages` has no text, sender link or timestamp. Sends without a draft (Ask link, confirmation, status) can't be shown in a conversation, and answers are placed at `drafts.approved_at`, not the actual send time. Proposed schema fix: add `follower_id`, `body` and `created_at` to `outbound_messages`.
