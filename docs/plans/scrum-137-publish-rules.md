# SCRUM-137: Publish rules for answered Q&A

Owner: **Arun** (part of SCRUM-133). Used by: **Ritvik** (SCRUM-143, publish in the Creator Workspace), **Chinmay**
(SCRUM-117, `store_qa` job), **Akshay** (publish route), **Arun** (SCRUM-145, SCRUM-146).
Safety Layer link: DAT01 (private by default, publishing needs approval and a privacy check).

---

## 1. Default: private

The `store_qa` job saves every delivered answer as a `knowledge_entries` row with `source = 'question'` and
`published = false` (`services/ai_worker/worker.py`, `_store_qa`). It runs right after delivery: the sender publishes
the job once the question is marked delivered (PR #48). Migration 013 keeps it to one row per question. A private row
can help the AI draft future answers for the same creator, but it never shows in the consumer app.

## 2. Who decides

| Role | Can publish | Can unpublish |
|---|---|---|
| Creator | Yes, her own answers, one at a time | Yes, her own |
| Admin (ProfessorDM staff) | Allowed by migration 014 today. **Open:** should only the creator publish? | Yes, any entry |
| Consumer, Instagram follower | No | No |

Sending an answer is **not** publishing it. They are two separate creator actions.

## 3. When an answer can be published

All of these must be true:

1. The answer was **delivered** to the follower (only delivered answers get an entry, section 1).
2. The question has **no open safety flag**. For now this is the only safety check possible, because the send flow
   skips the checkpoint-3 final screen.
3. The creator **explicitly chooses to publish** it.
4. The public version has **no follower details**: no name, @handle, Instagram id, photos or the original DM word for
   word. The public question starts as `question_text` and the creator edits it in the publish dialog.
5. It has **1 to 5 tags** (already required when sending).

**Server check for rule 4** (agreed Nov 21): the server rejects a publish if the title or content contains the
follower's `ig_followers.username`, or the original DM text word for word. This works now, without waiting for the AI
anonymizer, which is not in the repo yet.

## 4. What the consumer sees

Only `title` (the public question), `content` (the answer) and `tags`. Never `question_id`, the follower, the original
DM or anything from the `questions` table. Locked in by `apps/consumer/src/lib/knowledge/queries.test.ts` (SCRUM-146).

## 5. Unpublish and edits

Unpublishing sets `published = false`. The entry disappears from Home, Search, Topics and its Entry page on the next
load. To change a published answer: unpublish, edit, publish again, so section 3 is checked again.

## 6. Where the rules are enforced

| Layer | How | Status |
|---|---|---|
| Database read | RLS `knowledge_entries_select_published` (migration 008): consumers read `published = true` rows only | Done |
| Consumer app | Every read filters `published = true` and selects only `id, title, content, tags` | Done, tested (SCRUM-146) |
| Search function | `match_knowledge` defaults to `p_published_only = false`. Any consumer search endpoint **must** pass `true` | Rule for later |
| Publish write | `set_knowledge_entry_published` (migration 014): own `question` entries only, writes `audit_log` | Done (SCRUM-143) |
| Publish checks | Rules 3.2 and 3.4 checked on the server, plus the edit dialog | To build (section 8) |

## 7. Acceptance tests

| # | Test | Ticket |
|---|---|---|
| 1 | An unpublished row is hidden in Search, Home and by direct link | SCRUM-136 (passed Nov 12) |
| 2 | A published row shows its title, answer and tags, and nothing else | SCRUM-138 (passed Nov 12) |
| 3 | Unpublishing hides it again | SCRUM-138 (passed Nov 12) |
| 4 | A real delivered answer is saved private, then published from the Creator Workspace and shown in consumer search | SCRUM-139 |
| 5 | Consumer reads stay published-only, with no follower fields | SCRUM-146 (merged, PR #37) |
| 6 | A publish is rejected when the title or content contains the follower's username or the DM word for word | Follow-up |

## 8. Decisions and follow-ups

| # | Question | Decision |
|---|---|---|
| 1 | Public question text | Prefill from `question_text`; the creator edits it in the publish dialog (Ritvik) |
| 2 | Removing names | Server check from section 3 for now; automated anonymizer later (Safety Layer) |
| 3 | Who builds what | Ritvik: dialog and server action in the Creator Workspace. Akshay: server route, same split as `approveAnswer`. **Waiting for Akshay to confirm** |
| 4 | Demo | SQL update was the fallback; the SCRUM-143 Publish button now works, so the demo can use it |
| 5 | Timing | `store_qa` runs right after delivery (PR #48), but diagram 04 and the architecture README say "only after the 3-day hold, never if refunded". **Chinmay to confirm** which is right. If it stays right after delivery, a refunded question should not be publishable, and the diagrams need updating |
| 6 | Admin publishing | Migration 014 lets an admin publish. Keep it, or limit publishing to the creator? |
