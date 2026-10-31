# ai_worker: triage and drafting

Triage reads each Instagram DM a follower sends to a creator and decides what happens next: answer it as a paid expert question, ask the follower for more detail, route it to the creator, close it, or block it. Drafting then writes a reply to each paid question from the creator's own guides, for the creator to edit before sending (see [Drafting](#drafting)).

## Contents

1. [Overview](#overview)
2. [Quick start](#quick-start)
3. [API reference](#api-reference)
4. [How it decides](#how-it-decides)
5. [For Akshay: wiring it up](#for-akshay-wiring-it-up)
6. [For Ritvik: showing it in the creator workspace](#for-ritvik-showing-it-in-the-creator-workspace)
7. [For Karthik: infra, security and quality gates](#for-karthik-infra-security-and-quality-gates)
8. [Adding a new creator](#adding-a-new-creator)
9. [Changing the prompt safely](#changing-the-prompt-safely)
10. [Drafting](#drafting)
11. [For Akshay: wiring draft](#for-akshay-wiring-draft)
12. [For Ritvik: showing the draft](#for-ritvik-showing-the-draft)
13. [Knowledge base](#knowledge-base)
14. [Changing the draft prompt safely](#changing-the-draft-prompt-safely)
15. [Limitations](#limitations)
16. [Open questions](#open-questions)

## Overview

A follower DMs the creator. The backend loads that DM and the follower's recent DMs, then calls `triage()`. Triage runs three safety checks and a classifier, then returns **one decision**: a plain Python dict saying which status to set and what to create or send. The backend applies it to the database. Triage itself never touches the database, Instagram or anything else outside the model APIs.

When triage asks the follower a clarifying question and they reply, the backend calls `reassess()` instead. It looks at the original DM together with the questions and replies.

```
DM text (+ recent DMs from the same follower)
   │
   ├─ empty text? ───────────────────────────► awaiting_clarification ("describe it in words")
   │
   ├─ 1. moderation (OpenAI) ── severe? ─────► blocked + decline (crisis_text for self-harm)
   │                         └─ other hits ──► safety flags, continue
   ├─ 2. blocked terms ──────── match? ──────► blocked + decline
   │
   ├─ 3. classify (Gemini) ── category, confidence, service_kind, risk flag
   │        invalid twice ───────────────────► creator_decision
   │
   └─ route
        confidence < 0.6 ────────────────────► creator_decision
        safety_concern ──────────────────────► creator_decision + flag
        expert_question ─────────────────────► ready_for_question + question
        needs_clarification ─────────────────► awaiting_clarification + question to follower
                                               (creator_decision after 2 rounds)
        service_request ─────────────────────► service_routed
        social, spam_irrelevant ─────────────► closed_no_action
```

| File | What |
|---|---|
| `triage.py` | `triage()`, `reassess()`, routing, confidence cutoff. No HTTP |
| `draft.py` | `draft()`: grounded answer drafts, the similarity gate, answer validators, checkpoint 2. No HTTP |
| `knowledge.py` | `search()`: one query embedding plus the `match_knowledge` RPC, read-only |
| `safety.py` | Safety layers 1 and 2, shared with draft: moderation thresholds, severe categories, base blocked list, `screen()`. No HTTP (the moderation call is passed in) |
| `llm.py` | Model calls: moderation, classify, clarification text, `write_draft()` (primary plus manual fallback), `embed()` |
| `prompts.py` | Generic templates (triage, clarify, draft), the Sweetlife Flora profile, `profile_for()`, version strings |
| `ingest/` | Laptop-only scripts that turn the guides into knowledge base rows (see [ingest/README.md](ingest/README.md)) |
| `tests/` | Unit tests with fakes, no network: `test_triage.py` (the 46 triage tests, unchanged), `test_draft.py`, `test_knowledge.py`, `test_llm.py`, `test_safety.py`, `test_ingest.py`, `test_kb_eval.py`, `test_eval_draft.py` |

## Quick start

**Environment** (read at call time, never logged):

| Variable | Required | Purpose |
|---|---|---|
| `OPENAI_API_KEY` | yes | Moderation (`omni-moderation-latest`, free) and query embeddings (`text-embedding-3-small`) |
| `OPENROUTER_API_KEY` | yes | Classification, clarification text and drafts |
| `TRIAGE_MODEL` | no | Classifier override; defaults to `google/gemini-3.1-flash-lite` |
| `DRAFT_MODEL` | no | Draft primary override; defaults to `anthropic/claude-sonnet-5.5` |
| `DRAFT_FALLBACK_MODEL` | no | Draft fallback override; defaults to `openai/gpt-5.6-terra` |
| `SUPABASE_URL` | draft | The project URL, for the `match_knowledge` RPC |
| `SUPABASE_SERVICE_ROLE_KEY` | draft | Service-role key for that RPC (the function is granted to `service_role` only) |
| `KB_EXCLUDE_TAGS` | no | Comma-separated tags `search()` leaves out when the caller passes none: **empty on staging, `review:pending` in production** |

Locally, the keys live in the repo-root `.env`, which is git-ignored. Load it into the command that needs it, and never print it:

```bash
set -a; source .env; set +a; <command>
```

**Tests** (Python 3.11, no network, no keys needed):

```bash
uv run --python 3.11 python -m unittest discover services/ai_worker/tests
```

**Eval** (real models, about $0.10 for the full golden set; see [eval/README.md](../../eval/README.md)):

```bash
set -a; source .env; set +a; uv run --python 3.11 python eval/eval_triage.py
set -a; source .env; set +a; uv run --python 3.11 python eval/eval_triage.py --limit 10 --model google/gemini-3.5-flash-lite
```

**Try it interactively:**

```bash
cd services/ai_worker
set -a; source ../../.env; set +a; uv run --python 3.11 python
```

```python
>>> from triage import triage, reassess
>>> triage("my pothos has yellow leaves, it's by a north window and I water weekly")["status"]
'ready_for_question'
>>> d = triage("why is it yellow")
>>> d["status"], d["clarification"]
('awaiting_clarification', {'round': 1, 'prompt': 'Which plant are you growing, and how often are you watering it? ...'})
>>> reassess("why is it yellow", [{"round": 1, "prompt": d["clarification"]["prompt"],
...           "reply": "a pothos, north window, I water every week, started 2 weeks ago"}])["status"]
'ready_for_question'
```

## API reference

### `triage(text, recent_messages=None, profile=None) -> dict`

For a new DM that isn't a reply to an open clarification.

| Argument | Type | Meaning |
|---|---|---|
| `text` | `str \| None` | The DM text. `None` or blank (a photo-only DM) asks for a description in words, with no model call |
| `recent_messages` | `list[str] \| None` | The same follower's other DMs from the 30 minutes before this one, oldest first. Used so a question split across DMs is read as one. Only `text` is moderated |
| `profile` | `dict \| None` | The creator profile from `prompts.profile_for(creator_id)`. Defaults to `SWEETLIFE_FLORA` |

### `reassess(original_text, rounds, recent_messages=None, profile=None) -> dict`

For a follower's reply to a clarification question. The decision applies to the **original** message.

| Argument | Type | Meaning |
|---|---|---|
| `original_text` | `str \| None` | Text of the message that is `awaiting_clarification` |
| `rounds` | `list[dict]` | Every clarification round for it, with the new reply saved in the latest: `[{"round": 1, "prompt": "...", "reply": "..."}]`. At least one is required (otherwise `ValueError`). Any order |
| `recent_messages` | `list[str] \| None` | The follower's DMs from the 30 minutes before the original message |
| `profile` | `dict \| None` | As above |

Only the newest reply is moderated and checked for blocked terms; earlier text was screened when it arrived.

### The decision

Both functions return a dict with exactly these keys. Fields that don't apply are `None` or `[]`.

```python
{
    "status": "ready_for_question",
    "category": "expert_question",
    "service_kind": None,
    "confidence": 0.95,
    "reason": "Asks a specific care question about water quality for a named plant",
    "prompt_version": "triage-v4+sweetlife-v2",
    "model": "google/gemini-3.1-flash-lite",
    "safety_flags": [{"layer": "policy", "category": "risk_topic", "detail": "pesticides or chemical use"}],
    "question": {"question_text": "...", "safety_flagged": True},
    "clarification": None,
    "outbound": None,
}
```

| Field | Type | Meaning |
|---|---|---|
| `status` | `str` | The inbound status to set (see the statuses table below) |
| `category` | `str \| None` | One of the 6 categories. `None` only when the model failed twice |
| `service_kind` | `str \| None` | For `service_request` only: `platform`, `business` or `out_of_domain` |
| `confidence` | `float \| None` | The classifier's confidence, 0 to 1. `None` when no model decided (empty text, blocked, model failure) |
| `reason` | `str \| None` | One sentence explaining the label, for the creator. The prompt forbids quoting the DM or naming people |
| `prompt_version` | `str` | For example `triage-v4+sweetlife-v2`, or `triage-v4+clarify-v4+sweetlife-v2` when the model wrote a clarification |
| `model` | `str \| None` | The classifier id, `omni-moderation-latest` for a moderation block, `None` for a blocked term or empty text |
| `safety_flags` | `list[dict]` | `{"layer", "category", "detail"}`. `layer` is `moderation`, `rules` or `policy`. `detail` is `None` or one of the profile's risk topics, **never DM text** |
| `question` | `dict \| None` | With `ready_for_question` only: `{"question_text", "safety_flagged"}`. `question_text` joins the recent messages and the DM (or the original and every reply). `safety_flagged` is true if any flag exists |
| `clarification` | `dict \| None` | With `awaiting_clarification` only: `{"round": 1 or 2, "prompt": "..."}` |
| `outbound` | `dict \| None` | A DM to send: `{"type": "clarification" or "decline", "text": "..."}`. A self-harm block sends the profile's `crisis_text` as type `decline` |

### Categories

The categories mirror `MESSAGE_CATEGORIES` in `packages/contracts` (a test checks this).

| Category | Meaning |
|---|---|
| `expert_question` | An in-scope question clear enough to answer (a general how-to about a named subject counts) |
| `needs_clarification` | In scope, but missing key details: which plant, the symptom, light, watering, how long |
| `social` | No request: greetings, thanks, compliments, emoji, test messages, "who's this" |
| `spam_irrelevant` | Promotions, scams, bots, follow-for-follow, gibberish |
| `safety_concern` | Harm or an emergency: self-harm, threats, harassment, sexual content, hate, requests to hurt someone, or a person or pet that may need urgent medical help (even if not plant related) |
| `service_request` | Needs the creator or ProfessorDM to act rather than answer (see `service_kind`) |

### `service_kind` values

| Value | Meaning |
|---|---|
| `platform` | Refunds, the status of a paid question, payment or Ask link trouble |
| `business` | The profile's business topics: buying plants or cuttings, orders, shipping, workshops, collaborations, sponsorships |
| `out_of_domain` | A real question outside the creator's domain (protein powder, landscaping, a non-urgent vet question). It goes to the creator instead of being dropped as spam |

### Statuses triage can return

| Status | When |
|---|---|
| `ready_for_question` | A confident `expert_question`. The backend creates a `pending_payment` question |
| `awaiting_clarification` | `needs_clarification` (rounds 1 and 2), or a DM with no text |
| `closed_no_action` | `social` or `spam_irrelevant` |
| `service_routed` | `service_request` |
| `blocked` | A severe moderation hit or a blocked term. A decline is sent and nothing reaches payment |
| `creator_decision` | Low confidence, an unblocked `safety_concern`, still unclear after 2 rounds, or the model failed twice |

The backend sets `triaging` and `reassessing` itself around the call (see [For Akshay](#for-akshay-wiring-it-up)). `received` isn't used by triage.

### Exceptions

| Exception | When |
|---|---|
| `llm.LLMError` | OpenAI or OpenRouter failed: an HTTP error, a 10 s timeout, a network error or an unreadable response. Attributes: `service`, `status`, `code` |
| `RuntimeError` | An API key is missing from the environment |
| `ValueError` | `reassess` was called with no rounds |

## How it decides

1. **Empty text.** If there's no text (a photo-only DM), triage asks the follower to describe the problem in words using the profile's `empty_text_prompt`. There's no model call.
2. **Safety layer 1, moderation.** The DM goes to `omni-moderation-latest`. A category counts only if OpenAI flags it; the thresholds below then decide what happens.
3. **Safety layer 2, blocked terms.** A case-insensitive, whole-word regex runs over the base list in `safety.py` plus the profile's `extra_blocked_terms`. A match blocks and sends a decline.
4. **Classify (safety layer 3 included).** The classifier is called at temperature 0 with a strict JSON schema. It returns `category`, `service_kind`, `confidence`, `reason`, `risk_flag` and `risk_reason`. The `risk_flag` is the policy check: it marks a profile risk topic (such as pesticides) without blocking. Invalid output is retried once, then goes to `creator_decision`.
5. **Route.** Apply the routing table below.

### Moderation categories

| OpenAI category | What happens when OpenAI flags it |
|---|---|
| `self-harm/intent`, `self-harm/instructions` | **Block at any score**, replying with `crisis_text` (988 and local emergency services) |
| `sexual/minors` | **Block at any score**, replying with `decline_text` |
| `harassment/threatening`, `hate/threatening` | **Block at a score of 0.5 or more** (`SEVERE_FLAG_THRESHOLD`). Below 0.5, no flag; the classifier still sees the text and usually labels a real threat `safety_concern` |
| `illicit/violent` | **Flag only, never block**, at 0.5 or more. It fires on pest-killing language ("whats the best way to nuke them?? 💀" scored 0.80). A genuinely harmful request still reaches `creator_decision` through the classifier |
| `harassment`, `hate`, `illicit`, `self-harm`, `sexual`, `violence`, `violence/graphic` | **Flag only** at 0.5 or more (`MILD_FLAG_THRESHOLD`). Below 0.5, ignored. That keeps "how do I kill the fungus gnats" (violence 0.40) out of the Moderation tab |

Every threshold was calibrated on synthetic data only. Revisit them with real DMs.

### Routing table

The routing rules are checked in this order:

| Result | `status` | Also in the decision |
|---|---|---|
| Severe moderation hit or blocked term | `blocked` (category `safety_concern`) | `safety_flags`; `outbound` decline (`crisis_text` for self-harm) |
| `confidence` < 0.6 | `creator_decision` | Keeps the model's category; nothing sent |
| `safety_concern` | `creator_decision` | A `policy` / `safety_concern` flag; nothing sent |
| `expert_question` | `ready_for_question` | `question` |
| `needs_clarification`, rounds left | `awaiting_clarification` | `clarification` + `outbound` clarification |
| `needs_clarification`, 2 rounds used | `creator_decision` | reason "Still unclear after 2 clarification rounds" |
| `needs_clarification`, writing failed twice | `creator_decision` | reason "Model failed to write a clarification twice" |
| `service_request` | `service_routed` | `service_kind` |
| `social`, `spam_irrelevant` | `closed_no_action` | none |
| Invalid model output twice | `creator_decision` | `category` None, reason "Model returned invalid output twice" |

A risk flag or a mild moderation flag adds a `safety_flags` entry on any route and never changes the status. On `ready_for_question` it sets `question.safety_flagged`.

**Clarification text** is at most 2 short questions, under 200 characters, in the profile's voice. It never mentions photos, because triage only reads text. Text that breaks these rules is rejected and retried once.

**Why at most 2 rounds:** two questions give the follower a fair chance to add the missing details without turning a DM into an interview. After that, the creator is better placed to decide. The schema allows only rounds 1 and 2.

### Confidence cutoff

`CONFIDENCE_CUTOFF = 0.6`. Below it, the creator decides instead of the router. Every prediction on dev and test scored between 0.90 and 1.0, wrong ones included, so no cutoff catches errors yet. Eval prints a cutoff table at each 0.05 step to recalibrate once real DMs exist.

## For Akshay: wiring it up

### 1. Claim the message

`upsert_inbound` leaves `status` null. Claim the message with a conditional update, so two runs can't take the same one:

```
PATCH inbound_messages?id=eq.<id>&status=is.null
body {"status": "triaging"}, Prefer: return=representation
```

No row back means another run has it, so stop. This is the same pattern as `update_follower_username_if_missing`.

### 2. Choose `triage` or `reassess`

Call **`reassess`** if the follower has an open clarification: a message in `awaiting_clarification` whose latest `clarification_rounds` row has `reply is null`. The new DM is that round's reply. Otherwise call **`triage`**.

### 3. Build `recent_messages`

Use the same follower's `inbound_messages.text` with `received_at` in the 30 minutes before this message, oldest first. For `reassess`, the window is relative to the original. Leave out:
- the message itself
- `blocked` messages
- messages with no text
- clarification replies, which are already in `rounds`

### 4. Saving a clarification reply (before `reassess`)

1. Save the reply text into the open round's `reply`.
2. Set the reply's own `inbound_messages` row to `closed_no_action`.
3. Claim the original with `PATCH ...?id=eq.<original>&status=eq.awaiting_clarification`, setting `{"status": "reassessing"}`.
4. Call `reassess(original.text, all_rounds, recent, profile_for(creator_id))` and write the decision **to the original**.

### 5. Writing the decision

| Decision field | Table and columns |
|---|---|
| `status`, `category`, `confidence`, `prompt_version` | `inbound_messages` (the original for `reassess`) |
| `question` | New `questions` row: `creator_id`, `source='instagram'`, `follower_id`, `origin_message_id` = the message, `question_text`, `status='pending_payment'`, `safety_flagged`, `ask_token` (yours) |
| `clarification` | New `clarification_rounds` row: `message_id` = the original, `round`, `prompt`, `reply` null |
| `outbound` | New `outbound_messages` row: `type` (`clarification` or `decline`), `text`, `status='pending'`, `attempts=0`, `delivery_mode='standard'`, `inbound_message_id` = the original, `follower_id`, `creator_id` |
| `safety_flags` | One `safety_flags` row each: `target_type='message'`, `target_id` = the original, `checkpoint='1'`, `layer`, `category` (`status` defaults to `open`). `detail` has no column and isn't stored |
| `reason`, `model`, `service_kind` | **No columns yet** (requested from Karthik). Until then, log `model` and `service_kind`; keep `reason` out of logs because it summarizes the DM |

### 6. Pending outbound rows need a sender

Clarification, decline and `crisis_text` rows are written as `pending` `outbound_messages`. Nothing sends `pending` rows yet: `send_handler` only sends the creator's typed answers. Every outbound text is under Instagram's 1000-byte limit.

### 7. The Ask link is yours

For `ready_for_question`, generate the signed `ask_token` and send the `ask_link` DM. Triage doesn't create it.

### 8. Split-message duplicates

Suppose the follower already has a `pending_payment` question created in the last 30 minutes and the new decision is `ready_for_question`. Append this message's `text` to that question's `question_text` on a new line instead of creating a second question. Do this only while it's `pending_payment`, never after payment.

### 9. Errors and retries

- **`llm.LLMError`:** set the status back (null for `triage`, `awaiting_clarification` for `reassess`) and retry later with backoff. A saved clarification reply makes the retry safe.
- **No automatic decision on outages:** triage raises instead of returning a fallback, so an outage is never stored as a real result.
- **Retry limit:** once an `attempts` column exists, stop after about 3 failures and set `creator_decision`.
- **`RuntimeError`:** a key is missing, so fix the config.
- **`ValueError` from `reassess`:** there are no rounds, so call `triage`.
- **Timeouts:** each model call times out at 10 s. A typical decision takes 1.5 to 2.6 s; the worst case with retries is about 50 s. Give the Lambda a timeout of at least 60 s.

### 10. Logging

Log status, category, `service_kind`, confidence, `prompt_version`, `model` and error types. Never log DM text, `reason`, clarification text or keys. Triage's own logs follow the same rule.

## For Ritvik: showing it in the creator workspace

`labels.ts` already builds its labels from the contract lists, so every category and status triage returns has a label.

**What each category means for the creator**

| Category | For the creator |
|---|---|
| `expert_question` | A follower wants a paid answer; they get an Ask link |
| `needs_clarification` | Triage asked the follower for details; nothing to do yet |
| `social` | A greeting or thanks; visible, no reply needed |
| `spam_irrelevant` | Spam; visible, no reply |
| `safety_concern` | Needs the creator's eyes now (harm, threat or emergency) |
| `service_request` | Needs the creator to act: an order, a collab, a refund, or a question outside their domain |

**What each status means for the creator**

| Status | For the creator |
|---|---|
| `ready_for_question` | Waiting for the follower to pay |
| `awaiting_clarification` | Waiting for the follower's reply |
| `closed_no_action` | Done, nothing needed |
| `service_routed` | The creator's to-do: reply or act |
| `blocked` | Declined automatically; it never reaches payment |
| `creator_decision` | **Triage wasn't sure or wasn't allowed to act; the creator decides.** Show it prominently with the reason |

**Safety flags in the Moderation tab:** list `safety_flags` rows where `target_type='message'` and `status='open'`, joined to the message.

| `layer` | Show as |
|---|---|
| `moderation` | "Flagged by the safety filter", with the OpenAI category (for example `harassment`) |
| `rules` | "Matched a blocked term" |
| `policy` / `risk_topic` | A review reminder ("Involves pesticides"), not an accusation |
| `policy` / `safety_concern` | Urgent review |

A question with `safety_flagged = true` must be reviewed in Moderation before it's answered.

**`reason`** is one sentence written for the creator, for example "Asks whether a golden pothos is safe around a cat." It doesn't quote the DM. Show it next to the category once it has a column.

**`override_category`** is the creator's correction. The UI already prefers `override_category ?? category`. Its rate is our real accuracy metric, so please keep it easy to use.

**Clarification threads:** the clarification text is stored as `clarification_rounds.prompt` and the follower's answer as `reply`, both under the original message, as `buildThread` already shows them.

**Known issue, the reply shown twice:** a clarification reply is also its own `inbound_messages` row (set to `closed_no_action`), so it appears twice: once as a message and once as the round's reply. Hide inbound rows that are a round's reply, or link them; this needs a decision with Akshay.

## For Karthik: infra, security and quality gates

- **Secrets:** `OPENAI_API_KEY` and `OPENROUTER_API_KEY` belong in SSM (SecureString). The Lambda reads them as `runtime._parameter` does and puts them in `os.environ` before the first call. They're read at call time, never at import, and never logged. `TRIAGE_MODEL` is optional plain config.
- **Data collection:** every OpenRouter call (triage and draft) sends `provider: {"data_collection": "deny"}`, plus `require_parameters: true` with a schema, so only providers that don't retain prompts get real DMs. `eval/check_providers.py` confirms each model still finds one.
- **Runtime:** Python 3.11, standard library only (`urllib`, `json`, `re`, `time`, `os`, `logging`), with flat imports like `instagram_backend`. No packaging step.
- **Latency and cost per DM** (3.1 Flash-Lite, 202 eval DMs):
  - median 1.5 s, 90th percentile 2.5 s, 2.6 s when a clarification is written
  - about 1,560 tokens and **about $0.0005** per DM (about $0.49 per 1,000); moderation is free
  - 10 s timeout per call
- **Eval and the three bars:** `eval/eval_triage.py` reports dev and test separately (see [eval/README.md](../../eval/README.md)). The proposed bars, on the test split, are below. The latest result is **98.7% / 100% / 95.8%** on synthetic data (`triage-v4+sweetlife-v2`, 2026-10-30).
  - overall accuracy of 90% or more
  - `safety_concern` recall of 100%
  - `expert_question` precision of 90% or more
- **Baseline rule for prompt changes:** any change to `prompts.py`, the routing or the thresholds:
  - bumps `TRIAGE_VERSION` or `CLARIFY_VERSION`
  - is evaluated on dev **and** test
  - must keep test at or above the bars
  - records the before and after numbers in the PR

  Tuning on test examples isn't allowed (see [Changing the prompt safely](#changing-the-prompt-safely)).
- **Schema additions requested** (all on `inbound_messages` unless you prefer elsewhere):
  - `reason text`: the creator-facing explanation
  - `model text`: which model decided
  - `service_kind text`: platform, business or out_of_domain
  - `triage_attempts int`: so the backend can stop retrying after repeated `LLMError`s and hand the message to the creator
- **CODEOWNERS:** it lists `/services/ai-worker/`, but the folder is `services/ai_worker`, because Python modules can't contain hyphens. The rule doesn't match today.
- **Moderation thresholds:** `MILD_FLAG_THRESHOLD` and `SEVERE_FLAG_THRESHOLD` (both 0.5) and the flag-only `illicit/violent` rule were calibrated on synthetic data only. `omni-moderation-latest` can change under us, so re-run eval if flags shift.

## Adding a new creator

1. Copy `SWEETLIFE_FLORA` in `prompts.py` to a new dict, such as `NEW_CREATOR`, and fill in every field:

   | Field | What to write |
   |---|---|
   | `version` | `<short-name>-v1`; bump it on any change |
   | `creator_name`, `domain` | The display name and a phrase for their expertise |
   | `in_scope`, `out_of_scope` | What counts as an expert question, and what doesn't |
   | `clear_question_needs` | The details an answerable question needs (this drives clarifications) |
   | `service_topics` | Their business topics (shop, workshops, collabs) |
   | `risk_topics` | A **list** of short tags that need review but no block; they become the only allowed flag details |
   | `extra_blocked_terms` | Their own blocked phrases (a list, signed off by them) |
   | `voice` | The tone for clarification DMs |
   | `empty_text_prompt`, `decline_text`, `crisis_text` | The fixed replies (`crisis_text` needs sign-off) |
   | `examples` | 2 or 3 short DMs per category with labels (`kind` on service examples) |

2. Register it in `profile_for()`, for example `return PROFILES.get(creator_id, SWEETLIFE_FLORA)` with `PROFILES = {"<creators.id>": NEW_CREATOR}`.
3. Build a dev and test set for the new domain. `eval_triage.py` currently evaluates `SWEETLIFE_FLORA` only, so it would need a `--profile` option. The new creator's golden rows must not reuse their few-shot examples.
4. Never put domain words in `TRIAGE_TEMPLATE` or `CLARIFY_TEMPLATE`. A test checks the template stays generic.

## Changing the prompt safely

1. Edit the template, the profile or the routing. Then bump `TRIAGE_VERSION` or `CLARIFY_VERSION` (and the profile's `version` if you changed the profile).
2. Run the unit tests.
3. Run eval on both splits: `eval/eval_triage.py`, with both models if the change is meant to be model-agnostic.
4. Tune only on **dev**. If a test example looks wrong, add a *similar, new* example to dev and fix that. Never edit the prompt because of a specific test row, and never edit test rows.
5. Put the before and after numbers for dev and test, and the version strings, in the PR. That's the new baseline.

## Drafting

`draft()` turns one paid question into one decision: a reply the creator edits before sending, written only from passages of the creator's own guides, or the reason there's no draft. Like triage, it's pure decision logic. It searches the knowledge base and calls the models, then returns a dict. It never writes to the database or sends a DM. A draft only helps the creator: whatever happens, the question still goes to her.

```
paid question (+ clarification rounds)
   │
   ├─ blank? ─────────────────────────────────────► no_draft / empty_question
   ├─ search the guides (question + replies) ── best similarity < 0.475? ──► no_draft / no_coverage (no model call)
   ├─ write (Sonnet 5.5, Terra on an outage) ── invalid twice? ──► no_draft / invalid_output
   ├─ model says coverage "none" ─────────────────► no_draft / no_coverage (+ missing_info)
   ├─ checkpoint 2 on the answer ── severe or blocked term? ──► no_draft / safety_blocked (text dropped)
   └─ drafted: answer + citations + coverage + missing_info + flags
```

### `draft(question_text, *, creator_id, rounds=None, original_text=None, channel="instagram", safety_flagged=False, flagged_topics=None, profile=None, search=None, time_left=None) -> dict`

| Argument | From |
|---|---|
| `question_text` | `questions.question_text` |
| `creator_id` | `questions.creator_id` |
| `channel` | `questions.source` (`instagram` or `knowledge_app`); sets the length limit (1000 or 4000 bytes) |
| `safety_flagged` | `questions.safety_flagged`; adds a risk note to the prompt |
| `original_text` | `inbound_messages.text` where `id = questions.origin_message_id`; shown to the model only when it differs from the question |
| `rounds` | `clarification_rounds` rows (`round`, `prompt`, `reply`) for that message, any order |
| `profile` | `prompts.profile_for(creator_id)`; defaults to `SWEETLIFE_FLORA` |
| `flagged_topics` | The `detail` values of the origin message's checkpoint-1 `policy` / `risk_topic` flags. Values outside the profile's `risk_topics` are dropped, so DM text can never reach the prompt this way. With topics, the note names them; without, it's a generic "check the risk topics" line |
| `time_left` | Seconds left in the Lambda. `None` means no limit (eval and local runs). No model call (primary, fallback or retry) starts with fewer than 45 s left |
| `search` | Same contract as `knowledge.search`; `None` means `knowledge.search`. Tests and the eval pass their own |

### The decision

Every decision has exactly these keys:

```python
{
    "status": "drafted",                 # or "no_draft"
    "reason": None,                      # or "no_coverage" | "invalid_output" | "safety_blocked" | "empty_question"
    "draft": {"ai_text": "...", "citations": [
        {"kind": "knowledge", "ref": "<knowledge_entries.id>", "title": "Guide > Section", "hpa_id": "HPA-FUND-0001",
         "supports": "a few words on what it supports"}], "used_web_search": False},   # None for no_draft
    "knowledge_coverage": "partial",     # "high" | "partial" | "none"
    "missing_info": ["what the guides don't cover, as short topic phrases"],
    "safety_flags": [{"layer": "policy", "category": "risk_topic", "detail": "pesticides or chemical use"}],
    "model": "anthropic/claude-sonnet-5.5",   # the model that actually answered (may be the fallback); None without a call
    "prompt_version": "draft-v2+sweetlife-v2",
    "retrieved": [{"entry_id": "...", "title": "...", "similarity": 0.61}],   # logs and eval only, not stored
}
```

Coverage is `none` for an empty question, a gate stop and invalid output, and the model's own value for `safety_blocked`. `missing_info` is `[]` at the gate and the model's list otherwise. Citations are deduplicated by passage in order of first use.

### How it decides

1. **Channel.** An unknown channel raises `ValueError` before any call.
2. **Deadline.** `time_left` becomes an absolute deadline for the model calls.
3. **Empty question.** A blank `question_text` is `no_draft` / `empty_question`, with no search and no model call.
4. **Clean the inputs.** Rounds are sorted and their replies trimmed. `flagged_topics` is limited to the profile's risk topics.
5. **Search query.** The question plus every non-empty clarification reply, joined with newlines, cut to 2,000 characters.
6. **Retrieve.** `search(query, creator_id, k=8, sources=["doc"])`: the 8 best guide chunks, at most 3 per guide. Version 1 drafts from the Academy guides only, never from the 8 team-written demo Q&A answers.
7. **Gate.** If the best cosine similarity is below `DRAFT_MIN_SIMILARITY` (**0.475**, tuned on dev), the decision is `no_draft` / `no_coverage` and **no draft model is called**. The gate uses similarity, never the RRF score, which only measures rank position.
8. **Number the passages** `K1` to `Kn` in retrieval order and build this call's strict schema: the `ref` enum is exactly the refs sent and `risk_topics` is the profile's list.
9. **Build the user message.** The question, the original message (when it differs), the clarification rounds, the risk note when flagged, and the passages, every text JSON-quoted like triage.
10. **Write.** `llm.write_draft()` calls `DRAFT_MODEL` (no temperature, strict schema, `max_tokens` 2000, 45 s timeout). On a timeout, network error, 429, 404 or 5xx it calls `DRAFT_FALLBACK_MODEL` once (no temperature, `reasoning: {"effort": "low"}`, `max_tokens` 4000), if 45 s are still left. Both send `provider: {"data_collection": "deny", "require_parameters": true}`.
11. **Validate.** The fields must match the schema. Unless coverage is `none`, the answer must be non-empty and within the channel's byte limit. It must not contain markdown (`#` headings, `*`, backticks), URLs, `[K` markers, `[1]`-style citation numbers, internal guide ids, the whole word `AI`, `passage(s)` or `knowledge base`. Every cited ref must have been sent, with at least one cited, and risk topics must come from the profile. `- ` bullets, `1.` steps and the word "source" are allowed. On a failure there is one retry: the same messages plus a fixed line naming what failed, such as "too long, keep it under 900 characters". The rejected answer is never sent back. A second failure, or no time left for the retry, is `no_draft` / `invalid_output`. `missing_info` is clipped, never a failure: at most 5 phrases of at most 80 characters, cut at a word boundary.
12. **Coverage `none` from the model** is `no_draft` / `no_coverage`, keeping its `missing_info`.
13. **Checkpoint 2.** `safety.screen()` runs moderation and the blocked terms on the answer. Mild hits become flags, and each returned risk topic adds a `policy` / `risk_topic` flag. A severe category or blocked term drops the text: `no_draft` / `safety_blocked`, flags kept.
14. **Citations and log.** `used_sources` become citations with the entry id, title and hpa id. One log line is written: status, reason, coverage, passage count, best similarity, flag count, attempts, error codes, latency, tokens and cost. It contains no text.

### Exceptions

| Exception | When |
|---|---|
| `llm.LLMError` | OpenAI (embedding or moderation), OpenRouter (both draft models) or Supabase failed, or the first model call could not start in time (`("openrouter", None, "deadline")`). Never turned into a draft |
| `RuntimeError` | A key or Supabase setting is missing |
| `ValueError` | The profile has no byte limit for `channel` |

### Latency and cost (draft eval, offline search, `draft-v2+sweetlife-v2`)

| Split | Drafted | Mean latency | p90 latency | Mean cost per draft |
|---|---|---|---|---|
| dev (17 rows) | 11 | 9.3 s | 14.3 s | $0.0175 |
| test (28 rows) | 23 | 9.0 s | 13.1 s | $0.0177 |

The target is under $0.02 per draft. Gate stops cost only the query embedding. No eval draft needed the fallback. Quality numbers are in [eval/README.md](../../eval/README.md#draft-eval).

## For Akshay: wiring draft

1. **Job:** `{v: 1, type: "draft", id: "draft:<questionId>", creatorId, traceId, createdAt, payload: {questionId}}` on the ai-jobs queue, as its own job (never chained inside a triage run).
2. **Trigger:** when a question becomes `paid`. While payment is stubbed, the worker sets `pending_payment -> paid` right after creating the question and queues the draft job.
3. **Claim:** `PATCH questions?id=eq.<id>&status=eq.paid` -> `{"status": "drafting"}`. No row returned = someone else has it or it is done; acknowledge the job.
4. **Load** the inputs from the argument table in [Drafting](#drafting) and call `draft()`. Pass `time_left` (seconds left in the Lambda) and, once 009 is applied, `flagged_topics` = the `detail` values of the origin message's checkpoint-1 `policy/risk_topic` flags.
5. **Write, always one `drafts` row** (so Kristin sees why when there is no draft, and flags have a target):
   - `question_id`, `ai_text` (null for `no_draft`), `citations` (`[]` for `no_draft`), `used_web_search=false`, `model_used`, `prompt_version`, `status` (`ready` or `no_draft`), `knowledge_coverage`, `missing_info`, `reason`.
   - Before inserting, skip if a `drafts` row for this question with status `ready` or `no_draft` already exists (retry safety).
6. **Safety flags:** one `safety_flags` row per flag: `target_type='draft'`, `target_id=<drafts.id>`, `checkpoint='2'`, `layer`, `category`, `detail` (added in 009; a fixed vocabulary such as the risk topic, never DM text). If any flag exists, set `questions.safety_flagged = true`.
7. **Finish:** question -> `awaiting_creator` in every case. A draft only helps the creator; it never blocks her.
8. **Errors:** `LLMError` -> set status back to `paid`, let SQS retry with backoff (DLQ after 3). `RuntimeError` -> configuration problem, alert.
9. **Timeouts:** draft Lambda timeout 120 s (primary plus manual fallback); pass the remaining time to `draft()` as `time_left`. Queue visibility timeout 720 s (six times the function timeout, as AWS recommends for SQS triggers). Karthik and Akshay set this.
10. **Logs:** status, reason, coverage, ids, latency, cost. Never text.

The decision's `status` is `drafted` or `no_draft`; store `drafted` as `drafts.status = 'ready'`. `model` goes to `model_used`. `retrieved` isn't stored.

## For Ritvik: showing the draft

For a question in `awaiting_creator`, read its `drafts` row:
- `ready`: show `ai_text` pre-filled in the reply box (creator must edit), and the source titles from `citations`.
- `no_draft`: show "No AI draft, answer by hand" with the reason (`no_coverage`, `invalid_output`, `safety_blocked`) and `missing_info` as "what the guides don't cover".
- `knowledge_coverage` as a small badge; Safety Flag badge when `questions.safety_flagged` is true (flags listed in Moderation).

Citation titles look like `Guide title > Section > Subsection`. Checkpoint-2 flags are `safety_flags` rows with `target_type='draft'`; show them the same way as message flags.

## Knowledge base

- **Where the rows come from.** The ingest scripts in [`ingest/`](ingest/README.md) parse the creator's guides (`.docx`), cut them into section, table, callout and card chunks, embed them with `text-embedding-3-small` and write `knowledge_entries` rows (`source='doc'`, `published=false`, one `knowledge_docs` row per guide). Karthik loads them into Supabase with `load_kb.py`. The guides and everything derived from them live in git-ignored `private/` folders, because the repo is public.
- **Tags** are namespaced: `hpa:<guide id>`, `kind:section|table|callout|card`, `review:approved|pending`, `topic:<care topic>`. `search()` reads the guide id from the `hpa:` tag.
- **`match_knowledge`** (migration 010) is a hybrid search: cosine similarity plus Postgres full-text rank, merged with Reciprocal Rank Fusion. It filters by creator, source, published and excluded tags (rows with null tags are never excluded by accident). It returns `similarity` (cosine, what the gate uses) and `score` (RRF, for ordering only). Execute is granted to `service_role` only.
- **`knowledge.search()`** embeds the query (fail-fast), calls the RPC for 20 candidates, keeps at most 3 chunks per guide (Q&A rows each count on their own) and returns the top `k`. It's read-only, and every Supabase failure is an `LLMError`, so the worker retries it like a model outage.
- **`KB_EXCLUDE_TAGS`** is the default exclude list when the caller passes none: **empty on staging** (draft guides are allowed for testing) and **`review:pending` in production**, so guides the expert hasn't approved are never drafted from (spec decision D4). An explicit `exclude_tags=[]` always wins.

## Changing the draft prompt safely

The same rules as [triage](#changing-the-prompt-safely), with `DRAFT_VERSION`:

1. Edit `DRAFT_TEMPLATE`, the user message or the validators in `draft.py`, then bump `DRAFT_VERSION` (`draft-v2` -> `draft-v3`). If you change `answer_voice`, `answer_rules` or `max_answer_bytes`, bump the profile `version` too. That also changes triage's `prompt_version`, so rerun the triage eval.
2. Keep the template generic: no domain words (a test checks).
3. Run the unit tests, then `eval/eval_draft.py --split dev`.
4. Tune only on **dev**. Run test once per change and never change the prompt, the validators or the gate because of a test row. If a test row shows a real gap, add a similar dev row.
5. Drafts run without temperature, so numbers move a few points between runs. A change must beat the baseline by more than that noise.
6. Change `DRAFT_MIN_SIMILARITY` only after a new dev sweep (`eval/eval_draft.py --gate-sweep`).
7. Put dev and test numbers and the version strings in the PR.

## Limitations

- **Text DMs only.** There's no image or video understanding, and a photo-only DM just gets asked for words.
- **The eval is synthetic.** The test split was written by `claude-sonnet-5.5`, labeled blind by `gpt-6.1-sol` and reviewed by hand. Real accuracy will come from the creator's `override_category` rate once the inbox is live.
- **Placeholder content.** `crisis_text` and the blocked lists are placeholders until Kristin and Karthik sign off.
- **Unvalidated thresholds.** The moderation thresholds and the confidence cutoff haven't been checked against real traffic.
- **Self-harm hints.** Hints that moderation doesn't block (for example "idk who will water them when im not around") go to `creator_decision` with no automatic crisis reply.
- **Single creator.** `profile_for()` returns the same profile for every creator.

**Drafting:**
- **Draft quality bars not met yet.** On test, `draft-v2` drafts pass every automatic check but score 69.6% grounded (bar 90%) and 46.4% coverage accuracy (bar 80%). Most coverage misses are one step lower than the review label (`high` -> `partial`), and most unsupported claims are small extrapolations or reassurance. The creator always edits the draft before sending.
- **Placeholder voice and rules.** `answer_voice` and `answer_rules` were written from the Academy guides' style and are placeholders until Kristin signs off.
- **Model version.** The drafter is Sonnet 5.5 (`anthropic/claude-sonnet-5.5`), not the tech matrix's Sonnet 5. It's the same price; record it in Nova's decision log.
- **Arun's retrieval queries are pending** (SCRUM-91). The retrieval eval accepts them with no code change.
- **Production must exclude unreviewed guides.** Set `KB_EXCLUDE_TAGS=review:pending` there. Staging drafts from draft guides on purpose.
- **No web search.** `used_web_search` is always false; gaps go to the creator through `missing_info`.
- **Text only.** Figures are kept only as captions, and the follower's photos aren't read.
- **No drafts from Q&A in v1.** Drafts search `sources=["doc"]`, so the 8 team-written demo Q&A answers are never cited. Add `"question"` once real answered Q&A exist.
- **Small gate sample.** `DRAFT_MIN_SIMILARITY = 0.475` was tuned on 17 dev rows, 0.040 below the lowest answerable one. On test it stopped 2 answerable rows and let 2 out-of-KB rows through. Recheck it on real questions.

## Open questions

| Question | Owner |
|---|---|
| `crisis_text` wording (placeholder, mentions 988) | Kristin, Karthik |
| Emergency auto-reply: should pet or child emergencies and unblocked self-harm hints get an automatic "contact your vet / poison control / 988 now" message? | Kristin, Karthik |
| The final blocked list (`BLOCKED_TERMS` and `extra_blocked_terms`) | Kristin, Karthik |
| Should every pesticide question be flagged for review (`risk_topics`)? | Kristin |
| Claiming with a conditional update on `status is null` | Akshay |
| A sender for `pending` clarification, decline and crisis rows | Akshay |
| The `ask_link` DM and `ask_token` | Akshay |
| Split-message duplicates (append to a `pending_payment` question within 30 minutes) | Akshay |
| Where `reason`, `model` and `service_kind` live until columns exist | Akshay, Karthik |
| A clarification reply shown twice in the thread | Ritvik, Akshay |
| Schema columns: `reason`, `model`, `service_kind`, `triage_attempts` | Karthik |
| The CODEOWNERS path (`ai-worker` vs `ai_worker`) | Karthik |
| Re-calibrating the moderation thresholds and the confidence cutoff on real DMs | Karthik, Chinmay |
| Sign-off on `answer_voice` and `answer_rules` (placeholders) | Kristin |
| Sonnet 5.5 instead of the tech matrix's Sonnet 5 (same price), for the decision log | Nova, Chinmay |
| Arun's 10 retrieval queries (SCRUM-91) | Arun, Karthik |
| `KB_EXCLUDE_TAGS=review:pending` in production | Karthik |
| Draft Lambda timeout 120 s, queue visibility timeout 720 s | Karthik, Akshay |
| Draft quality below the grounded and coverage bars: tune further on dev, or accept for v1 since the creator edits every draft | Chinmay, Karthik |
| Rechecking `DRAFT_MIN_SIMILARITY` on real paid questions | Chinmay |
