# Final answer screen: shared contract (v2.1, Nov 22)

Owner: Chinmay (AI layer). This is the one source of truth for Akshay (send API), Ritvik (Creator Workspace) and Karthik (infra and database). If it changes, Chinmay updates this file and tells all three. A copy lives in the repo at `docs/final-answer-screen.md` once the AI branch merges.

**v2 changes:** Karthik's decision is applied, the screen has an 11 second deadline, every confirm case has its own row, checkpoint-3 rows are tied to the outbound message, and retries are covered.

## What it is

SAF01 says the exact final text that goes to a follower must be screened, including the creator's edits and her manual replies. The AI layer gives the send API one call that screens a text and returns a decision. The AI layer holds the OpenAI and OpenRouter keys. The send Lambda never needs them.

The screen has three layers:
1. **Moderation:** OpenAI `omni-moderation-latest` with the same thresholds as triage and drafts.
2. **Blocked terms:** the base list plus the creator's own terms.
3. **Answer rules:** a small model call that checks the text against the creator's `answer_rules`. This catches dangerous advice moderation misses, for example telling someone a pet that chewed a toxic plant is fine.

Layers 1 and 3 run at the same time.

**Decision (Karthik, Nov 22):**
- A mild issue (a mild moderation hit or a broken answer rule): the creator sees a warning and can confirm and send.
- A severe issue or a blocked term: blocked, with no override.
- Each confirm-and-send is logged (counts only, never text).

## How to call it

- **Lambda:** the function name comes from env var `SAFETY_SCREEN_FUNCTION`. Karthik adds the function to `ai-worker.yaml`. Invoke it synchronously (`InvocationType=RequestResponse`).
- **Code:** handler `screen_handler.lambda_handler` in `services/ai_worker`.
- **For Dec 1:** only the send API calls it.

Request payload:

```json
{
  "text": "the exact text that will be sent",
  "creator_id": "uuid",
  "channel": "instagram",
  "question_text": "the follower's question, or null for a manual reply",
  "trace_id": "optional string for logs"
}
```

- **`text`:** the caller builds the final text **once** and uses that same string for the screen, the hash and the send. The screen hashes it exactly as given, with no stripping. 1 to 4000 characters.
- **`channel`:** `instagram`. `knowledge_app` is accepted but nothing sends it before Dec 1.
- **`question_text`:** pass it for answers, because some rules depend on the question (a pet ate a plant). Null for manual replies.

## The response

```json
{
  "decision": "PASS",
  "next_actor": "none",
  "reason_codes": [],
  "categories": [],
  "rules": [],
  "flags": [],
  "text_sha256": "hex sha256 of text, UTF-8",
  "check_version": "final-check-v1+sweetlife-v2",
  "model": "model id used for the answer-rules check, or null",
  "latency_ms": 900
}
```

| decision | next_actor | reason_codes that cause it | Meaning |
|---|---|---|---|
| `PASS` | `none` | (empty) | Nothing found. `flags` may still hold `risk_topic` flags (information only) |
| `BLOCK` | `creator` | `moderation_severe`, `blocked_term` | Severe or blocked phrase. No override |
| `HOLD` | `creator` | `moderation_mild`, `answer_rule` | Mild issue. The creator may confirm and send |
| `HOLD` | `system` | `check_unavailable` | A check failed, gave bad output twice, or didn't finish within the deadline |

Branch on decision and next_actor only (v2.1). reason_codes, categories, rules and flags list every finding from every check that finished, whatever the decision. So a BLOCK can also list answer_rule, moderation_mild or check_unavailable. A HOLD/system can also list moderation_mild or answer_rule. Show them all, but never decide from them.

Decision order: BLOCK, then HOLD/system, then HOLD/creator, then PASS. A creator can't confirm past a check that didn't run. A blocked term still gives BLOCK when moderation is down, because the term check is local.

**Fields:**
- **`categories`:** moderation category names (for example `harassment`, `violence`) and `blocked_term`. Never text.
- **`rules`:** the broken answer rules, as `{"id": "R2", "text": "<the rule, from the creator profile>"}`. The rule text is creator config, not message text.
- **`flags`:** rows to save as checkpoint 3 when the text is sent. Each is `{"layer", "category", "detail"}`:

  | Finding | layer | category | detail |
  |---|---|---|---|
  | Moderation hit | `moderation` | the OpenAI category | null |
  | Blocked term | `rules` | `blocked_term` | null |
  | Broken answer rule | `policy` | `answer_rule` | rule id, for example `R2` |
  | Risk topic the reply covers | `policy` | `risk_topic` | the topic |

  A blocked term always means `BLOCK`, so a `rules` flag never gets sent or saved at checkpoint 3. The row is listed only so everyone uses the same values.
- **Deadline:** 11 seconds overall. Anything not finished by then gives `HOLD/system` with `check_unavailable`. The function timeout is 15 seconds; set the invoke read timeout to 14 seconds. An invoke error, timeout, `FunctionError`, unreadable payload or `{"error": "invalid_request"}` all mean `check_unavailable`.

## Send API mapping (Akshay owns this, including the `confirm_final_sha256` request field)

Every request that would send is screened again, including a confirming request, and the decision comes from that new result. The UI never hashes: it echoes the `text_sha256` from the 422 as `confirm_final_sha256`.

| New screen result | Request | HTTP response | Sent? | Checkpoint-3 rows |
|---|---|---|---|---|
| `PASS` | any (with or without a confirm) | as today | yes | its `risk_topic` flags, `status='open'` |
| `BLOCK` | any | `422 {"error": "final_blocked", "categories": [...], "rules": [...]}` | no | none |
| `HOLD/creator` | no `confirm_final_sha256` | `422 {"error": "final_flagged", "categories": [...], "rules": [...], "text_sha256": "<new>"}` | no | none |
| `HOLD/creator` | `confirm_final_sha256` equals the new `text_sha256` | as today | yes | all its flags, `status='creator_reviewed'`, `reviewed_by` = creator, `reviewed_at` = now |
| `HOLD/creator` | `confirm_final_sha256` doesn't match (text changed) | `422 final_flagged` with the new hash | no | none |
| `HOLD/system`, or the invoke failed | any | `503 {"error": "safety_check_unavailable"}` | no | none |

## Checkpoint-3 rows

- **Which flags:** always the flags from the screen that let this request send. Never an older result.
- **Columns:**
  - `target_type='final'`, `target_id` = the `outbound_messages.id` reserved for this send, `checkpoint='3'`;
  - `layer`, `category` and `detail` from the flag.
- **Both paths:** this works for answers and manual replies, because both reserve an outbound row.
- **Database:** Karthik adds `reviewed_at` and `created_at` to `safety_flags`, and changes the read policy so `final` rows are matched through `outbound_messages` instead of `drafts`.

## Retries can't double send

- **Screening comes first.** The screen runs before anything is claimed or reserved.
- **On a 422 or 503,** nothing was reserved, so a retry with the same `client_request_id` is safe.
- **At most one send:** the existing unique reservation on `client_request_id` guarantees it.
- **If the client timed out but the server already reserved and sent,** the retry hits today's early return. That's no new screen and no second send.

## Rules every caller follows

- **Fail closed:** send only on `PASS`, or on `HOLD/creator` with a matching confirmation.
- **No text anywhere:** never log text, and never store it in flags.

## AI layer notes (not part of the contract)

Everything above is the contract, copied as agreed. This section is the AI layer's own notes for whoever picks the work up next. Nothing here changes the contract.

### Where the code is

| File | What |
|---|---|
| `services/ai_worker/screen_handler.py` | The Lambda entry: checks the payload, loads the two keys from SSM once per container, logs one summary line |
| `services/ai_worker/final_screen.py` | `screen_final()`: runs the checks on two threads under the 11 second deadline and combines the findings. No HTTP |
| `services/ai_worker/llm.py` | `check_answer_rules()`: the one model call for layer 3 |
| `services/ai_worker/prompts.py` | `FINAL_CHECK_TEMPLATE`, `FINAL_CHECK_VERSION`, `answer_rule_ids()` |
| `services/ai_worker/safety.py` | Layers 1 and 2, shared with triage and drafts (unchanged) |
| `eval/eval_final_screen.py` | The seeded-hazard eval (see [eval/README.md](../eval/README.md)) |

The flow, the decision table and the function's env vars are in [services/ai_worker/README.md](../services/ai_worker/README.md#final-screen-checkpoint-3).

### Run it locally with fakes

No keys and no network. From the repo root:

```bash
cd services/ai_worker
uv run --python 3.11 python -c "
import json, final_screen
from prompts import SWEETLIFE_FLORA
print(json.dumps(final_screen.screen_final(
    'She will be completely fine.', question_text='My cat chewed a leaf.', profile=SWEETLIFE_FLORA,
    moderate=lambda text: {},
    check_rules=lambda text, question, profile: {'broken_rules': ['R2'], 'risk_topics': [], 'model': 'fake'}),
    indent=2))"
```

It prints a `HOLD` for the creator with rule `R2`. Change what the two lambdas return to see the other decisions: `moderate` returns moderation categories with scores (for example `{'harassment/threatening': 0.9}`), and `check_rules` returns rule ids and risk topics.

### Run it live

This calls the real models (a fraction of a cent). From the repo root:

```bash
set -a; source .env; set +a
cd services/ai_worker
uv run --python 3.11 python -c "
import json, final_screen, llm
from prompts import SWEETLIFE_FLORA
print(json.dumps(final_screen.screen_final(
    'Mix one part of the concentrate with ten parts water and spray weekly.',
    question_text='How do I treat spider mites?', profile=SWEETLIFE_FLORA,
    moderate=llm.moderate,
    check_rules=lambda text, question, profile: llm.check_answer_rules(text, question, profile, timeout=llm.TIMEOUT)),
    indent=2))"
```

To see the exact Lambda response, with `latency_ms`, call the handler the same way: `screen_handler.lambda_handler({"text": "...", "creator_id": "<any uuid>", "channel": "instagram"}, None)`. On a laptop it logs one `config_error` line, because boto3 and SSM are not set up there, and then uses the keys already in the environment.

The whole seeded set: `uv run --python 3.11 python eval/eval_final_screen.py --live` (27 screens, under one cent).

### Latency and cost

From the live eval on 2026-11-22: 27 screens, `final-check-v1+sweetlife-v2`, answer-rules model `google/gemini-3.1-flash-lite`, moderation `omni-moderation-latest`, run from a laptop.

| Measure | Value |
|---|---|
| Latency p50 | 886 ms |
| Latency p95 | 1186 ms |
| Slowest screen | 1597 ms |
| Cost per screen | $0.000234 (moderation is free) |
| Cost for all 27 | $0.00632 |

Both checks run at the same time, so a screen takes about as long as its slower call. These numbers leave a wide margin under the 11 second deadline.

### Timing

```
send Lambda timeout 28 s
└─ invoke read timeout 14 s
   └─ screen function timeout 15 s
      └─ screen deadline 11 s   (final_screen.SCREEN_DEADLINE_SECONDS)
         ├─ moderation       up to 10 s (llm.TIMEOUT)
         └─ rules check      up to 10 s, plus one retry only if 3 s or more remain
```

- The send Lambda in `infra/oct16-send-api.yaml` has `Timeout: 20` today. The contract needs 28. That file is Karthik's.
- A model call still running at the deadline is left to finish on its own thread. Its result is thrown away and never changes a response.

### For Karthik: the function

The Makefile target is `build-SafetyScreenFunction`, so the SAM logical id must be `SafetyScreenFunction` (with `BuildMethod: makefile` and `CodeUri: ../services/ai_worker/`, like `AiWorkerFunction`).

| Setting | Value |
|---|---|
| Handler | `screen_handler.lambda_handler` |
| Runtime | Python 3.11, no packaging step (standard library plus the runtime's boto3) |
| Timeout | 15 seconds |
| Env vars | `SSM_OPENAI_KEY`, `SSM_OPENROUTER_KEY` (the SSM parameter names, as on `AiWorkerFunction`); optional `TRIAGE_MODEL` |
| Permissions | `ssm:GetParameter` (with decryption) on those two parameters. No Supabase, no SQS |
| Caller | The send Lambda needs `lambda:InvokeFunction` on it and the env var `SAFETY_SCREEN_FUNCTION` |

### Logs

The handler writes one summary line per call. It is the record for that call:

```
Final screen decision=HOLD next_actor=creator reasons=answer_rule categories=none rules=R2 flags=1 text_chars=58 question_chars=41 channel=instagram model=google/gemini-3.1-flash-lite latency_ms=873 check_version=final-check-v1+sweetlife-v2 trace_id=abc-123
```

- No line ever holds the text, the question or a key. `trace_id` is cut to 64 characters and stripped to letters, digits and `._:-`.
- `llm.py` also logs one line per model call, and a failed check adds `Final screen stage=<screen|rules> FAIL error_type=<type>` (a missing key adds `Final screen config_error ...`).
- A call that outlives the deadline is logged as `error_type=deadline` in time. When it ends later, it can write its `llm.py` line, and a second `FAIL` line if it ends in an error, during another request on the same container. So don't read those lines as belonging to the request around them.

### Known gaps

- **SAF04 approval binding.** The screen returns `text_sha256`, and the send API compares it with `confirm_final_sha256`. Binding an approval to a stored record (who approved which text, when) is not built.
- **The Moderation page does not show checkpoint 3.** The rows are saved by the send API, but nothing in the Creator Workspace lists them yet.
- **Publishing to the knowledge app (SCRUM-143) is not screened.** `knowledge_app` is an accepted channel, but only the send API calls the screen for Dec 1.
- **The answer rules are placeholders** until Kristin signs off. They are append-only from now on, because stored flags name a rule by position (`R2` is the second rule).
- **Layer 3 checks rules, not correctness.** Layer 3 checks only the creator's `answer_rules`. It does not judge whether advice is correct, so a dangerous reply that breaks no listed rule (for example, unsafe chemical advice that names no ratio, dose or brand) passes layer 3. This is on purpose, to keep false holds low. The fix is more rules from Kristin, not a looser prompt.
- **Rule 3 almost never fires.** It starts "When the passages say...", and the screen sees only the reply and the question, never the passages. The template lists such a rule only when the reply plainly contradicts it.
- **The eval is a smoke set.** 27 hand-written rows, not the SCRUM-128 holdout. On the 2026-11-22 run every hazard was held or blocked and one benign reply of 14 was held (a blunt reply held for rule 4).
- **Moderation thresholds are calibrated on synthetic data only,** the same as for triage and drafts.
