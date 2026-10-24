# ai_worker: triage

Decides what happens to an inbound Instagram DM. Pure decision logic: it never reads or writes Supabase and never sends anything. You load the data, call one function, and write the returned decision to the tables.

Python 3.11, standard library only, flat modules like `services/instagram_backend`.

| File | What |
|---|---|
| `triage.py` | `triage()`, `reassess()`, routing, thresholds, base blocked list |
| `llm.py` | The only file with HTTP calls: OpenAI moderation, OpenRouter classify and clarification |
| `prompts.py` | Generic templates, the Sweetlife Flora profile, `profile_for()`, version strings |
| `tests/test_triage.py` | Unit tests with a fake `llm`, no real model calls |

## Setup

Environment variables, read at call time, never logged:

| Variable | Required | Notes |
|---|---|---|
| `OPENAI_API_KEY` | yes | Moderation (`omni-moderation-latest`) |
| `OPENROUTER_API_KEY` | yes | Classification and clarification text |
| `TRIAGE_MODEL` | no | Defaults to `google/gemini-3.1-flash-lite` |

In Lambda, load the keys from SSM the way `runtime._parameter` does and put them in `os.environ` before the first call.

Each model call times out after 10 s. A typical triage takes about 2 s (moderation, classify, and a clarification when needed). The worst case is about 50 s (one retry each), so give the Lambda a timeout of at least 60 s.

## Calling it

```python
from prompts import profile_for
from triage import reassess, triage

decision = triage(text, recent_messages, profile_for(creator_id))
decision = reassess(original_text, rounds, recent_messages, profile_for(creator_id))
```

**Which one:** call `reassess` when the follower has an open clarification, meaning one of their messages is `awaiting_clarification` and its latest `clarification_rounds` row has `reply is null`. The new DM is the reply to that round. Otherwise call `triage`.

**Inputs**

- `text`: the DM text. `None` or empty (a photo-only DM) is fine: the follower is asked to describe it in words, with no model call.
- `recent_messages`: the same follower's other DMs from the **30 minutes** before this one, as a list of strings, oldest first. Leave out the message itself, `blocked` messages and messages with no text. People often split one question across several DMs.
- `original_text`: the text of the message that is `awaiting_clarification`.
- `rounds`: every `clarification_rounds` row for the original, with the new reply saved in the latest one: `[{"round": 1, "prompt": "...", "reply": "..."}]`. It needs at least one round, otherwise it raises `ValueError`.

## Bookkeeping around the call

**New message (`triage`)**

1. Claim it with a conditional update, so two runs can't take the same message: `PATCH inbound_messages?id=eq.<id>&status=is.null` with `{"status": "triaging"}` and `Prefer: return=representation`. No row back means another run has it, so stop. (`upsert_inbound` leaves `status` null today.)
2. Call `triage`, then write the decision (below).
3. On any exception, set `status` back to null and retry later.

**Clarification reply (`reassess`)**

1. Save the reply text into the open round's `reply`, and set the reply message to `closed_no_action`.
2. Claim the original: `PATCH ...?id=eq.<original>&status=eq.awaiting_clarification` with `{"status": "reassessing"}`.
3. Call `reassess` with all the original's rounds, then write the decision **to the original message**.
4. On any exception, set the original back to `awaiting_clarification`. The reply is already saved, so the retry sees it.

## The decision

Every call returns one dict with this shape. Fields that don't apply are `None` or `[]`.

```python
{
    "status": "ready_for_question",
    "category": "expert_question",
    "service_kind": None,
    "confidence": 0.94,
    "reason": "Asks why monstera leaves yellow at the edges",
    "prompt_version": "triage-v4+sweetlife-v1",
    "model": "google/gemini-3.1-flash-lite",
    "safety_flags": [{"layer": "policy", "category": "risk_topic", "detail": "plants toxic to pets or kids"}],
    "question": {"question_text": "...", "safety_flagged": True},
    "clarification": None,
    "outbound": None,
}
```

| Field | Values |
|---|---|
| `status` | `ready_for_question`, `awaiting_clarification`, `closed_no_action`, `service_routed`, `blocked`, `creator_decision` |
| `category` | One of the 6 `MESSAGE_CATEGORIES`. `None` only when the model failed twice |
| `service_kind` | `platform` (refund, paid-question status, payment or link trouble), `business` (shop, orders, workshops, collabs) or `out_of_domain`. `None` unless the category is `service_request` |
| `confidence` | 0 to 1. `None` when no model decided (empty text, blocked, model failure) |
| `reason` | One model-written sentence for the creator. The prompt forbids quoting the DM or naming people, but it still summarizes the DM, so store it rather than log it |
| `prompt_version` | For example `triage-v4+sweetlife-v1`, or `triage-v4+clarify-v4+sweetlife-v1` when a clarification was written |
| `model` | Classifier model id, `omni-moderation-latest` for a moderation block, `None` for a blocked-term match |
| `safety_flags` | `layer` is `moderation`, `rules` or `policy`. `detail` is `None` or a profile risk topic, never DM text |
| `question` | Only with `ready_for_question`. For `reassess`, `question_text` joins the original and every reply |
| `clarification` | Only with `awaiting_clarification`: `{"round": 1 or 2, "prompt": "..."}` |
| `outbound` | `{"type": "clarification" or "decline", "text": "..."}`. A self-harm block sends the profile's `crisis_text` as a `decline` |

`creator_decision` happens when:
- confidence is below `CONFIDENCE_CUTOFF` (0.6)
- the category is `safety_concern` without a block
- the message is still unclear after 2 rounds
- the model returned invalid output twice

Nothing is sent; the creator decides from Incoming.

## Writing it to the tables

| Decision field | Where it goes |
|---|---|
| `status`, `category`, `confidence`, `prompt_version` | `inbound_messages` (the original message for `reassess`) |
| `question` | New `questions` row: `source='instagram'`, `status='pending_payment'`, `question_text`, `safety_flagged`, `origin_message_id`, `follower_id`, `creator_id`, plus an `ask_token` you generate |
| `clarification` | New `clarification_rounds` row: `message_id` = the original, `round`, `prompt`, `reply` null |
| `outbound` | New `outbound_messages` row: `type`, `text`, `status='pending'`, `attempts=0`, `delivery_mode='standard'`, `inbound_message_id` = the original, `follower_id`, `creator_id` |
| `safety_flags` | One `safety_flags` row each: `target_type='message'`, `target_id` = the original, `checkpoint='1'`, `layer`, `category`. `detail` has no column and isn't stored |
| `reason`, `model`, `service_kind` | No column yet (open question for Karthik). Until then, log `model` and `service_kind`, and keep `reason` out of logs |

**Split messages:** if the follower already has a `pending_payment` question created in the last 30 minutes and the new decision is `ready_for_question`, append this message's `text` to that question's `question_text` (on a new line) instead of creating a second question. Do this only while it's `pending_payment`, never after payment.

## Errors

| Raised | Meaning | What to do |
|---|---|---|
| `llm.LLMError` | OpenAI or OpenRouter failed: HTTP error, timeout or network. Has `service`, `status`, `code` | Reset the status as above and retry later |
| `RuntimeError("Missing ...")` | A key isn't in the environment | Fix config |
| `ValueError` | `reassess` was called with no rounds | Call `triage` instead |

Invalid model output is handled inside: one retry, then `creator_decision`. Logs from this package contain only stages, statuses, categories, confidence, flag counts, latency and error types, never DM text or keys.

## Not built here (yours)

- Sending: nothing picks up `pending` clarification or decline rows yet. `send_handler` only sends the creator's typed answers.
- The `ask_link` DM for `ready_for_question` (it needs your `ask_token`).
- The `platform` service requests (refund or status replies): today they only land in Incoming as `service_routed`.

## Tests and eval

```bash
python3 -m unittest discover services/ai_worker/tests
python3 eval/eval_triage.py --limit 20   # real models, needs both keys
```
