# SCRUM-140: Decide on flagged DMs in Moderation, with the decision recorded

> Git rule for this ticket: Claude commits each part on `feat/SCRUM-140-moderation-decisions` and never pushes.
> Ritvik pushes. Ritvik runs migration 012 in the Supabase SQL editor.

## Why

"Needs your decision" on `/moderation` lists DMs the AI handed to the creator (`inbound_messages.status =
'creator_decision'`), mostly safety concerns and low-confidence messages. Today each row only links to the conversation.
Nothing records what the creator decided, so the row and the Moderation tab count never go away.

## What the creator sees

Each row in "Needs your decision" gets two buttons next to the existing "Open the conversation" link:

```
@monstera.mom                                   Nov 17, 2:04 PM
Is my monstera safe for my cat to chew on?
[Safety concern]   AI note: possible pet poisoning
Open the conversation →
[ I replied ]  [ No reply needed ]
```

- **I replied**: she answered it herself in the conversation (manual reply, which already exists).
- **No reply needed**: she is leaving it on purpose.

Either button saves the decision. The row leaves the list, and the Moderation count drops by 1. If saving fails, the
row stays and shows "Couldn't save your decision. Try again."

## Goals / non-goals

- Goal: one click decides a DM, and the decision (who, which, when) is stored in `audit_log`.
- Non-goal: turning a DM into a paid question. That needs the AI worker to re-route it (Akshay/Chinmay), so it's a later ticket.
- Non-goal: decisions on flagged **questions** (they are reviewed in the answer composer) or on flagged answers (admin review, FLOW 6).
- Anti-goal: a decided DM must never reappear or be decided twice. Double clicks and two open tabs record one decision.

## Approaches considered

1. **Picked: database function, migration 012.** `record_message_decision(message_id, decision)` is `security definer`
   and called from a server action with the creator's session. In one transaction it checks ownership with the
   existing `current_creator_id()` / `is_admin()`, moves the DM to `closed_no_action`, marks its open checkpoint-1
   flags `creator_reviewed`, and writes the audit row. No Lambda deploy, and it stays in Ritvik's workstream.
2. A new send-API route (Python Lambda). It matches how answers are written, but needs a SAM deploy by Akshay for a
   database-only change.
3. An RLS update policy plus direct updates from the server action. This isn't atomic, and creators could write any column.

## Data

- Status: `creator_decision` → `closed_no_action`. These are existing values in `packages/contracts`, so there is no enum change.
  Closed DMs are already left out of the AI's recent-message context (`RECENT_SKIP_STATUSES`).
- Flags: `safety_flags` with `target_type='message'`, `target_id=<message id>`, `status='open'` →
  `status='creator_reviewed'`, `reviewed_by=auth.uid()`.
- Audit: `audit_log(actor_id=auth.uid(), action='message.decided', entity='inbound_message', entity_id=<id>,
  before_after={"decision": "replied"|"no_reply_needed", "before": "creator_decision", "after": "closed_no_action",
  "flags_reviewed": n})`. No DM text, matching the `answer.approved` row the send API writes.
- Return value: `'recorded'`, or `'already_decided'` when the DM is no longer `creator_decision` (nothing is written).
  Errors: `not_authenticated`, `invalid_decision`, and `not_found` (missing or another creator's).

## Builder's calls

- Admins may decide too, matching the read policies.
- Error copy, the server action shape and the component split follow the existing inbox code.
