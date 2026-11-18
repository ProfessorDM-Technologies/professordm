# SCRUM-143: Creator chooses whether to publish a delivered answer

> Git rule for this ticket: Claude commits each part on `feat/SCRUM-143-publish-delivered-answer` and never pushes.
> Ritvik pushes. Ritvik runs migration 014 in the Supabase SQL editor.

## Why

Answered questions are saved as `knowledge_entries` rows (`source = 'question'`, `question_id`, `title`, `content`,
`tags`). Chinmay's store job saves them after delivery as private (`published = false`); migration 013 keeps it to one
row per question. The consumer Knowledge app shows only `published = true` rows. The creator decides which of her
answers go public. Agreed with Karthik on Nov 18: build the button now, against existing test rows. When the store job
goes live, its rows appear in the list with no change here.

## What the creator sees

`/knowledge` → "Answers from your questions" replaces the placeholder:

```
How often should I water a calathea?                         [Private]
Keep the soil lightly moist, never soggy. In most homes…
[calathea] [watering]
                                                        [ Publish ]
-----------------------------------------------------------------------
Is my monstera safe for my cat?                            [Published]
Monstera leaves irritate a cat's mouth…
                                                   [ Make private ]
```

- **Publish**: the entry shows in the Knowledge app. **Make private**: it's hidden again.
- If saving fails, the row stays as it was and shows "Couldn't save. Try again."
- Empty list: "Answers you send are saved here as private entries. Publish the ones you want in the Knowledge app."

## Goals / non-goals

- Goal: one click publishes or unpublishes an answer entry. Each change (who, which, when) is stored in `audit_log`.
- Non-goal: creating entries (Chinmay's store job), editing text or tags, guide chunks (`source = 'doc'`), manual facts.
- Anti-goal: a creator must never publish another creator's entry or a guide chunk.

## Design (same pattern as SCRUM-140)

Migration 014 adds `set_knowledge_entry_published(p_entry_id uuid, p_published boolean) returns text`. It is
`security definer` and runs as the signed-in creator. In one transaction it:
- locks the row
- checks that `source = 'question'` and that the entry is hers (`creator_id = current_creator_id()`) or the caller is an admin
- sets `published`
- writes `audit_log(action = 'knowledge.published' | 'knowledge.unpublished', entity = 'knowledge_entry', before_after = {"before": bool, "after": bool, "question_id": uuid|null})`, with no answer text

It returns `'updated'`, or `'unchanged'` when the entry is already in that state (nothing written). Errors use the same
codes as migration 012: `28000` not signed in, `22023` missing value, `P0002` not found (missing, another creator's,
or not a question entry).

The page reads the entries through the existing RLS policy `knowledge_entries_select_creator_or_admin`. A server
action calls the function with the creator's session and refreshes the page.

## Builder's calls

- List order: newest delivered question first, then entries without a question, by title.
- Title falls back to the first line of the content.
