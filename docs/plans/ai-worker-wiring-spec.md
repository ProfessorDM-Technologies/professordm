# AI worker wiring: implementation spec

**Owner:** Akshay (backend). **Reviewer:** Karthik (infra, security). **Consulted:** Chinmay (AI modules), Ritvik (inbox).
**Goal:** a follower's Instagram DM goes all the way to an AI draft waiting for the creator, on staging:

```
DM → webhook → ai-jobs queue → AI WORKER: triage → question → (payment stub) → draft job
   → AI WORKER: draft → drafts row → question awaiting_creator → creator inbox → creator sends
```

Everything to the left of "AI WORKER" and the final send already runs on staging. Chinmay's `triage()`,
`reassess()` and `draft()` are merged and tested. This spec adds the worker that calls them and saves the
results, plus a sender for the automated replies (clarification, decline) the worker creates.

This spec was checked line by line against `main` at `a194bf5`, the staging database schema, the deployed
CloudFormation stacks and the creator-workspace queries. Where this spec and an older document disagree, this
spec wins. Section 14 lists every such difference.

---

## 0. Rules for the coding agent

1. **Only create or change the files listed in section 2.** Every other file is read-only. If a task seems to need
   a change anywhere else, **stop and ask** instead of changing it.
2. **No new dependencies.** Python 3.11 standard library only. `boto3` (present in the Lambda runtime) may be
   imported **only** in `services/ai_worker/handler.py` and `services/instagram_backend/outbound_handler.py`, and
   only inside functions in `handler.py`, so tests can run without it.
3. **No database migrations.** Every column and value this spec uses already exists on staging (section 4).
4. **Never log DM text, clarification text, answer text, `reason` values or keys.** Log ids, statuses, categories,
   counts, latency and error type names only. This matches `services/ai_worker/README.md` and
   `services/instagram_backend`.
5. **Never call Instagram twice for the same outbound row.** The claim rules in section 8 guarantee this.
6. **Every job must be safe to run twice.** SQS can deliver a job more than once, and the webhook publishes a new
   job every time Meta retries. Section 5 says how each step stays safe.
7. **Use the status and type names exactly as written here.** They come from `packages/contracts/src/index.ts`.
8. When anything is unclear, **stop and ask Karthik**. Do not guess.

---

## 1. What exists today (do not rebuild)

| Piece | Where | State |
|---|---|---|
| Webhook Lambda `professordm-webhook` | stack `professordm`, template `infra/active-webhook.yaml`, code `services/instagram_backend/` (`handler.py` → `runtime.webhook_handler` → `webhook.handle_webhook`) | Live. Saves `ig_followers` + `inbound_messages` (status left **null**), publishes a triage job |
| ai-jobs queue | `professordm-inbound` + DLQ `professordm-inbound-dlq` (maxReceiveCount 3), same stack | Live. **Nothing reads it.** Visibility timeout 60 s |
| Triage job message | `clients.SqsPublisher.publish` | `{"v":1,"type":"triage","id":"triage:<messageId>","creatorId":"<uuid>","traceId":"<uuid4>","createdAt":"<iso>","payload":{"messageId":"<uuid>"}}` |
| Send API `POST /api/send` | stack `professordm-staging-oct16-send`, template `infra/oct16-send-api.yaml` | Live. Creator-typed answers only. Checks the creator's login |
| AI modules | `services/ai_worker/` `triage.py`, `draft.py`, `knowledge.py`, `llm.py`, `prompts.py`, `safety.py` | Merged (PRs #20 to #22). Pure decision logic: no database writes, no Instagram |
| Knowledge base | `knowledge_docs`, `knowledge_entries`, `match_knowledge()` | Loaded on staging (migrations 009 and 010 applied) |
| SSM parameters | `/professordm/staging/supabase-url` (String), `/professordm/staging/supabase-service-role-key`, `/professordm/staging/openai-api-key`, `/professordm/staging/openrouter-api-key`, `/professordm/staging/instagram-profile-tokens/<igUserId>` (SecureString) | All present. Karthik created the two AI keys |
| Unused Node stack `professordm-staging-instagram-inbound` | | 0 calls. **Leave it alone** in this phase |

---

## 2. Files

### Create

| File | Purpose |
|---|---|
| `infra/ai-worker.yaml` | New SAM template, stack `professordm-ai-worker`: worker Lambda, outbound queue + DLQ, outbound sender Lambda, alarms (section 9) |
| `services/ai_worker/Makefile` | SAM build that copies only the top-level `*.py` files (section 9.2) |
| `services/ai_worker/handler.py` | Lambda entry: loads secrets, reads the SQS record, calls `worker.run_job`, reports failures (section 7) |
| `services/ai_worker/worker.py` | Job logic for `triage`, `reassess` and `draft` (sections 5 and 6). No boto3 |
| `services/ai_worker/db.py` | Small PostgREST client and the queries the worker needs (section 4.3). No boto3 |
| `services/ai_worker/tests/test_worker.py` | Unit tests with fakes (section 11) |
| `services/instagram_backend/outbound.py` | Outbound job logic: claim the row, send through Meta, record the result (section 8) |
| `services/instagram_backend/outbound_handler.py` | Lambda entry for the outbound sender |
| `services/instagram_backend/tests/test_outbound.py` | Unit tests with fakes |

### Change

| File | Change |
|---|---|
| `infra/active-webhook.yaml` | **One line:** `InboundQueue.Properties.VisibilityTimeout: 60` → `720`. Nothing else |
| `docs/architecture/BASELINE.md` | Section 2.2, the `outbound` row: extra fields become `outboundMessageId` (the sender reads `text`, `follower_id` and `creator_id` from the row). Add one sentence under the table: "The ai-worker also accepts `triage` jobs for clarification replies and runs reassess itself; the webhook does not need to send `reassess`." |

### Do not edit (read-only for this work)

- `services/ai_worker/triage.py`, `draft.py`, `knowledge.py`, `llm.py`, `prompts.py`, `safety.py`, `README.md`, `ingest/**`, existing tests
- `services/instagram_backend/webhook.py`, `handler.py`, `send_handler.py`, `sender.py`, `clients.py`, `runtime.py`, existing tests
- `infra/oct16-send-api.yaml`, `supabase/**`, `apps/**`, `packages/**`, `eval/**`, `.github/**`

---

## 3. Job messages

Every message uses the BASELINE envelope: `{"v": 1, "type", "id", "creatorId", "traceId", "createdAt", "payload"}`.
Serialize with `json.dumps(job, separators=(",", ":"))`, as `SqsPublisher` does. `createdAt` is
`datetime.now(timezone.utc).isoformat()`. `traceId` is copied from the job that caused it, so one DM keeps one
trace id end to end.

| Queue | `type` | `id` | `payload` | Producer | Consumer |
|---|---|---|---|---|---|
| ai-jobs (`professordm-inbound`) | `triage` | `triage:<messageId>` | `{"messageId"}` | webhook (exists) | ai-worker |
| ai-jobs | `reassess` | `reassess:<messageId>` | `{"messageId"}` | none yet. Accepted and handled exactly like `triage` | ai-worker |
| ai-jobs | `draft` | `draft:<questionId>` | `{"questionId"}` | ai-worker (payment stub). Later the Stripe webhook | ai-worker |
| outbound (`professordm-outbound`) | `clarification` or `decline` (the row's `type`) | `outbound:<outboundMessageId>` | `{"outboundMessageId"}` | ai-worker | outbound sender |

Unknown `v`, unknown `type`, malformed JSON or a missing payload id: log `job=invalid` with the type name only,
and **acknowledge** (do not retry; it can never succeed).

---

## 4. Database facts the worker relies on (checked on staging)

### 4.1 Tables and columns used

| Table | Columns used |
|---|---|
| `inbound_messages` | `id`, `follower_id`, `text`, `status`, `received_at`, `category`, `confidence`, `reason`, `model`, `service_kind`, `prompt_version`, `triage_attempts` (int, default 0). **No `creator_id` column** |
| `ig_followers` | `id`, `creator_id`, `ig_scoped_id` |
| `clarification_rounds` | `id`, `message_id` (→ inbound_messages), `round` (CHECK 1 to 2), `prompt`, `reply`. No unique index |
| `questions` | `id`, `creator_id`, `source` (`instagram`), `follower_id`, `origin_message_id`, `question_text` (NOT NULL), `status` (NOT NULL), `safety_flagged`, `paid_at`. No `created_at` column. `ask_token` stays null |
| `drafts` | `id`, `question_id`, `ai_text`, `citations` (jsonb), `used_web_search`, `model_used`, `prompt_version`, `status`, `knowledge_coverage` (CHECK high/partial/none), `missing_info` (jsonb, default `[]`), `reason` (CHECK no_coverage/invalid_output/safety_blocked/empty_question). No unique index |
| `outbound_messages` | `id`, `type` (CHECK includes clarification, decline), `text`, `status`, `attempts`, `delivery_mode` (CHECK standard/…), `inbound_message_id`, `follower_id`, `creator_id`, `draft_id` (null), `client_request_id` (**UNIQUE**), `meta_message_id` |
| `safety_flags` | `target_type` (CHECK message/draft/…), `target_id`, `checkpoint` (CHECK '1'/'2'/'3'), `layer` (CHECK moderation/rules/policy), `category`, `detail`, `status` (default `open`) |

All `status` columns are plain text with no CHECK, so the values below are accepted. Use only these:

- `inbound_messages.status`: null (webhook), `received` (old seed rows), `triaging`, `reassessing`, `ready_for_question`, `awaiting_clarification`, `closed_no_action`, `service_routed`, `blocked`, `creator_decision`
- `questions.status`: `pending_payment`, `paid`, `drafting`, `awaiting_creator`
- `drafts.status`: `ready`, `no_draft`
- `outbound_messages.status`: `pending`, `sent`, `failed` (the values the send API already uses)

### 4.2 Data already on staging: do not touch

- 18 `inbound_messages` with null status are older DMs whose jobs expired. **Do not backfill them.** Only jobs on the queue are processed.
- Seed questions (`delivered`, `accepted`, `awaiting_creator`) and drafts (`approved`) belong to the demo data. The worker only ever claims a question in `paid`, so it never touches them.

### 4.3 `db.py`

A PostgREST client in the same style as `instagram_backend/clients.py` (`urllib`, JSON, `urlencode` for query
strings, so ISO timestamps with `+` are encoded). Headers: `apikey` and `Authorization: Bearer <service key>`,
`Content-Type: application/json`, plus `Prefer` when given. Timeout 8 s.

```python
class DbError(Exception):           # .status (int | None), .code (str | None)

class Db:
    def __init__(self, url, service_key, timeout=8): ...
    def request(self, method, path, *, params=None, body=None, prefer=None): ...  # returns parsed JSON or None
```

- HTTP errors raise `DbError(status, code)`, where `code` is PostgREST's `code` field (`23505` = unique violation).
- Network errors and timeouts raise `DbError(None, "network")`.
- The URL must be `https`.

Keep every query the worker needs as a small method on `Db` (or plain functions taking `db`), so tests can fake
them. The exact queries are written out in sections 5 and 6. Use PostgREST syntax exactly as shown, for example
`params={"id": f"eq.{id}", "or": "(status.is.null,status.eq.received)"}`.

---

## 5. Triage job (`type` = `triage` or `reassess`)

Inputs: `message_id = payload["messageId"]`, `trace_id`, and `receive_count` (the SQS attribute
`ApproximateReceiveCount`, as an int).

### 5.1 Load and check

1. `GET inbound_messages?id=eq.{message_id}&select=id,follower_id,text,status,received_at,triage_attempts&limit=1`.
   No row: log and acknowledge.
2. `GET ig_followers?id=eq.{follower_id}&select=id,creator_id,ig_scoped_id&limit=1`.
   `creator_id = follower.creator_id`. If it differs from the envelope's `creatorId`, log `creator_mismatch` and
   use the follower's value.
3. `profile = prompts.profile_for(creator_id)`.

### 5.2 Is this a reply to an open clarification?

```
GET inbound_messages?follower_id=eq.{follower_id}&status=eq.awaiting_clarification
    &id=neq.{message_id}&received_at=lt.{message.received_at}
    &select=id,text,received_at,triage_attempts&order=received_at.desc&limit=1
```

If a row `O` comes back:

```
GET clarification_rounds?message_id=eq.{O.id}&select=id,round,prompt,reply&order=round.asc
```

If the **highest** round has `reply` null, this message is a reply to `O`: go to **5.5 (reassess path)**.
Otherwise go to **5.3 (triage path)**.

### 5.3 Triage path

1. **Claim** the message:
   ```
   PATCH inbound_messages?id=eq.{message_id}&or=(status.is.null,status.eq.received)
   body {"status": "triaging"}   Prefer: return=representation
   ```
   If `receive_count > 1`, use `or=(status.is.null,status.eq.received,status.eq.triaging)` instead. A redelivery
   means the earlier attempt died mid-job, and every write below is safe to repeat.
   **No row back:** another run has it, or it is done. Acknowledge.
2. **Recent messages** (so a question split across DMs is read as one):
   ```
   GET inbound_messages?follower_id=eq.{follower_id}&id=neq.{message_id}
       &and=(received_at.gte.{received_at - 30 min},received_at.lt.{received_at})
       &select=text,status&order=received_at.asc
   ```
   Keep rows with non-empty `text` whose `status` is **not** `blocked` and **not** `closed_no_action`.
   (Clarification replies are set to `closed_no_action` in 5.5, so this also leaves them out, as the README asks.)
   `recent = [row.text for row in kept]`.
3. **Call** `decision = triage.triage(message.text, recent, profile)`.
4. **Write the decision** (5.4) with `target_id = message_id`.

### 5.4 Writing a triage or reassess decision

`origin` is the message the decision belongs to: this message for triage, `O` for reassess. Write **in this order**.
Each step is safe to repeat.

| # | When | Write | Idempotency |
|---|---|---|---|
| a | `decision["safety_flags"]` not empty | One `safety_flags` row per flag: `target_type='message'`, `target_id=origin.id`, `checkpoint='1'`, `layer`, `category`, `detail` | First `GET safety_flags?target_type=eq.message&target_id=eq.{origin.id}&checkpoint=eq.1&select=layer,category,detail`. Insert only flags whose `(layer, category, detail)` is not already there |
| b | `decision["clarification"]` | `clarification_rounds`: `message_id=origin.id`, `round`, `prompt`, `reply=null` | Skip if `GET clarification_rounds?message_id=eq.{origin.id}&round=eq.{round}` returns a row |
| c | `decision["outbound"]` | `outbound_messages`: `type` (`clarification` or `decline`), `text`, `status='pending'`, `attempts=0`, `delivery_mode='standard'`, `inbound_message_id=origin.id`, `follower_id`, `creator_id`, `draft_id=null`, `client_request_id=uuid5(OUTBOUND_NS, f"{origin.id}:{type}:{round or 0}")` | On `DbError` 409 / `23505`, `GET outbound_messages?client_request_id=eq.{id}&select=id` and use that row |
| d | `decision["question"]` | `questions`: `creator_id`, `source='instagram'`, `follower_id`, `origin_message_id=origin.id`, `question_text`, `status='pending_payment'`, `safety_flagged` | Skip the insert if `GET questions?origin_message_id=eq.{origin.id}&select=id,status&limit=1` returns a row; use that row |
| e | after d, and only if env `PAYMENT_STUB == "true"` | `PATCH questions?id=eq.{q}&status=eq.pending_payment` → `{"status":"paid","paid_at":<now iso>}` | Conditional on `pending_payment` |
| f | after c | Publish the outbound job (section 3) | The sender's claim makes duplicates harmless |
| g | after e, if the question's status is `paid` | Publish the draft job (section 3) | The draft claim makes duplicates harmless |
| h | always, **last** | `PATCH inbound_messages?id=eq.{origin.id}&status=eq.{triaging or reassessing}` → `status`, `category`, `confidence`, `reason`, `model`, `service_kind`, `prompt_version` from the decision | Conditional on the in-progress status |

`OUTBOUND_NS` is a fixed `uuid.UUID` constant defined once in `worker.py`. Generate it once, paste it as a literal,
and never change it. It makes the outbound row id deterministic, so a retried job finds the same row instead of
sending twice.

Why this order: jobs (f, g) are published before the final status write (h). A crash after publishing only causes
a harmless duplicate. A crash before h leaves `triaging`, which the redelivered job re-claims (5.3 step 1).

With `PAYMENT_STUB` off, the question stays `pending_payment` and no draft job is sent. The Ask link and the
split-message merge (README "For Akshay" item 8) belong to the Stripe phase and are **not** part of this spec.

### 5.5 Reassess path (this message `M` is a reply to `O`)

1. **Claim the reply** `M` exactly as in 5.3 step 1. No row back: acknowledge.
2. **Claim the original:**
   ```
   PATCH inbound_messages?id=eq.{O.id}&status=eq.awaiting_clarification → {"status":"reassessing"}
   ```
   If `receive_count > 1`, use `or=(status.eq.awaiting_clarification,status.eq.reassessing)`.
   **No row back** (someone else is already reassessing `O`): keep `M` claimed as `triaging` and continue at
   5.3 step 2, triaging `M` as a new message.
3. **Rounds in memory:** the rows from 5.2, with the highest round's `reply` set to `M.text` (or `""` if null).
   **Do not save the reply yet.**
4. **Recent messages** for the **original**: the query from 5.3 step 2 with `O.id` and `O.received_at`.
5. **Call** `decision = triage.reassess(O.text, rounds, recent, profile)`.
6. **On success, in order:**
   - Save the reply: `PATCH clarification_rounds?id=eq.{round.id}&reply=is.null {"reply": M.text}`. Saving only
     when the reply is still null makes a repeat harmless.
   - Write the decision (5.4) with `origin = O` and the in-progress status `reassessing`.
   - Close the reply: `PATCH inbound_messages?id=eq.{M.id}&status=eq.triaging {"status":"closed_no_action"}`.

`ValueError` from `reassess` (no rounds) cannot happen after 5.2, but if it does: reset `O` to
`awaiting_clarification`, keep `M` as `triaging`, and continue at 5.3 step 2.

### 5.6 Failures

| Error | What to do |
|---|---|
| `llm.LLMError` | Reset statuses: triage path `M` → null; reassess path `O` → `awaiting_clarification` and `M` → null (each conditional on its in-progress status). Then `PATCH` the origin's `triage_attempts` to the value read + 1. If that is **≥ 3**: set the origin to `creator_decision` with `reason = "AI unavailable after 3 attempts"`, close `M` as `closed_no_action` on the reassess path (and save the reply as in 5.5 step 6), then **acknowledge**. Otherwise **retry** (section 7) |
| `DbError` | Best-effort reset as above, without changing `triage_attempts`. **Retry** |
| `RuntimeError` (missing key or setting) | Log `config_error`, best-effort reset, **retry**. After 3 deliveries it lands in the DLQ and the alarm fires |
| Anything else | Log the type name, best-effort reset, **retry** |

---

## 6. Draft job (`type` = `draft`)

Input: `question_id = payload["questionId"]`.

1. **Claim:**
   ```
   PATCH questions?id=eq.{question_id}&status=eq.paid → {"status":"drafting"}   Prefer: return=representation
   ```
   If `receive_count > 1`: `or=(status.eq.paid,status.eq.drafting)`. No row back: acknowledge.
   The returned row gives `creator_id`, `source`, `origin_message_id`, `question_text` and `safety_flagged`. Ask
   for them with `select=` on the PATCH.
2. **Load:**
   - `GET inbound_messages?id=eq.{origin_message_id}&select=text` gives `original_text`
   - `GET clarification_rounds?message_id=eq.{origin_message_id}&select=round,prompt,reply` gives `rounds`
   - `GET safety_flags?target_type=eq.message&target_id=eq.{origin_message_id}&checkpoint=eq.1&layer=eq.policy&category=eq.risk_topic&select=detail`
     gives `flagged_topics` = the non-null `detail` values
3. **Call:**
   ```python
   decision = draft.draft(question_text, creator_id=creator_id, rounds=rounds, original_text=original_text,
                          channel=source, safety_flagged=safety_flagged, flagged_topics=flagged_topics,
                          profile=prompts.profile_for(creator_id),
                          time_left=context.get_remaining_time_in_millis() / 1000 - 15)
   ```
   The 15 s reserve leaves time for the writes below.
4. **Write one `drafts` row,** unless `GET drafts?question_id=eq.{question_id}&status=in.(ready,no_draft)&select=id&limit=1`
   already returns one (then reuse it and skip to step 6):

   | Column | `drafted` | `no_draft` |
   |---|---|---|
   | `question_id` | question_id | question_id |
   | `status` | `ready` | `no_draft` |
   | `ai_text` | `decision["draft"]["ai_text"]` | null |
   | `citations` | `decision["draft"]["citations"]` | `[]` |
   | `used_web_search` | `false` | `false` |
   | `model_used` | `decision["model"]` | `decision["model"]` (may be null) |
   | `prompt_version` | `decision["prompt_version"]` | same |
   | `knowledge_coverage` | `decision["knowledge_coverage"]` | same |
   | `missing_info` | `decision["missing_info"]` | same |
   | `reason` | null | `decision["reason"]` |

   `decision["retrieved"]` is **not** stored.
5. **Checkpoint-2 flags:** for each `decision["safety_flags"]`, insert a `safety_flags` row with
   `target_type='draft'`, `target_id=<drafts.id>`, `checkpoint='2'`, `layer`, `category`, `detail`. Use the same
   "insert only missing" check as 5.4a. If any flag exists, `PATCH questions?id=eq.{question_id} {"safety_flagged": true}`.
6. **Finish:** `PATCH questions?id=eq.{question_id}&status=eq.drafting {"status":"awaiting_creator"}`.
   This happens in **every** outcome. A missing draft never blocks the creator.

**Failures**

| Error | What to do |
|---|---|
| `llm.LLMError` (OpenAI, OpenRouter, Supabase search or `deadline`) | If `receive_count >= 3`: question → `awaiting_creator` with **no drafts row**, log `draft_unavailable`, acknowledge. Otherwise question → `paid` (conditional on `drafting`) and **retry** |
| `DbError` | Question → `paid` (best effort) and **retry** |
| `ValueError` (unknown channel) | Question → `awaiting_creator`, no drafts row, log `bad_channel`, acknowledge |
| `RuntimeError` | Log `config_error`, question → `paid`, **retry** |

"No drafts row" is how the inbox recognises "AI unavailable". The `drafts.reason` CHECK has no outage value, and
adding one would need a migration, which is out of scope.

---

## 7. `handler.py`: the Lambda entry

```python
def lambda_handler(event, context):
    # BatchSize is 1, but loop anyway.
    failures = []
    for record in event.get("Records", []):
        outcome = _process(record, context)      # "done" or "retry"
        if outcome == "retry":
            _backoff(record)                     # see below; never raises
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}
```

- **Secrets, loaded once per container and cached:** read SSM names from the env vars `SSM_SUPABASE_URL`,
  `SSM_SUPABASE_KEY`, `SSM_OPENAI_KEY` and `SSM_OPENROUTER_KEY` with `WithDecryption=True`. Set
  `os.environ["SUPABASE_URL"]`, `["SUPABASE_SERVICE_ROLE_KEY"]`, `["OPENAI_API_KEY"]` and
  `["OPENROUTER_API_KEY"]` before the first call. Those are the names `llm.py` and `knowledge.py` read at call
  time. Never log the values.
- **`_process`:** parse the body (section 3 validation), read `receive_count = int(record["attributes"]["ApproximateReceiveCount"])`,
  then call `worker.run_job(job, receive_count=…, db=…, publish=…, time_left=…)`, where `publish(queue_url, job)`
  sends one message with boto3 SQS. `worker.run_job` returns `"done"` or `"retry"` and never raises. It catches
  everything per sections 5.6 and 6.
- **`_backoff`:** `sqs.change_message_visibility(QueueUrl=AI_JOBS_QUEUE_URL, ReceiptHandle=…, VisibilityTimeout=60 * receive_count)`,
  so a retry comes after about 1 then 2 minutes instead of 12. Catch and log any error here; the retry still
  happens at the normal visibility timeout.
- **One log line per job:** `AI worker job=<type> id=<job id> trace=<traceId> outcome=<done|retry> status=<final status> latency_ms=<n>`.
  `triage.py` and `draft.py` already log their own decision lines without text.

---

## 8. Outbound sender (`outbound.py`, `outbound_handler.py`)

Sends the automated `clarification` and `decline` rows the worker creates. It reuses the existing Instagram code
**without changing it**.

`outbound_handler.py`:

```python
from runtime import _supabase, _profile_ssm          # existing helpers, unchanged
from clients import MetaGraph, SsmProfileTokens, SupabaseRepository
from outbound import handle_outbound
# lambda_handler: for each record → handle_outbound(job, rest=_supabase(timeout=3), repository=SupabaseRepository(rest),
#   profile_tokens=SsmProfileTokens(_profile_ssm, os.environ["SSM_INSTAGRAM_PROFILE_TOKEN_PREFIX"]),
#   graph=MetaGraph(os.environ["META_GRAPH_API_VERSION"]))
# returns {"batchItemFailures": [...]} like the worker
```

`handle_outbound(job, *, rest, repository, profile_tokens, graph)` returns `"done"` or `"retry"`:

1. Validate the envelope. `type` must be `clarification` or `decline`. Anything else: log and acknowledge. Answers
   are sent only by `POST /api/send`.
2. `rest.request("GET", "outbound_messages", params={"id": f"eq.{id}", "select": "id,type,text,status,attempts,follower_id,creator_id", "limit": "1"})`.
   No row, or `status != "pending"`, or `attempts != 0`: acknowledge (already handled).
3. `follower = repository.get_follower(row.follower_id)` and `account = repository.get_ig_account(row.creator_id)`.
   If either is missing or `follower.creator_id != row.creator_id`, mark the row `failed` and acknowledge.
4. Text check: stripped, non-empty, at most 1000 UTF-8 bytes (the limit `sender.py` uses). Otherwise mark it `failed` and acknowledge.
5. **Claim:** `PATCH outbound_messages?id=eq.{id}&status=eq.pending&attempts=eq.0 {"attempts": 1}` with
   `return=representation`. No row back: acknowledge. **Nothing before this step calls Meta.** Errors before the
   claim return `"retry"`.
6. `token = profile_tokens.for_account(account["ig_user_id"])`, then `graph.validate_send_account(token, ig_user_id)`,
   then `graph.send(token, ig_user_id, follower["ig_scoped_id"], text)`.
7. Success: `repository.update_outbound(id, status="sent", meta_message_id=…, attempts=1)`.
   Any exception in step 6: `repository.update_outbound(id, status="failed", attempts=1)`, then acknowledge.
   **Never** retry after the claim. A duplicate DM is worse than a failed one; the creator sees `failed` in the thread.
8. Logs: outbound id, type, outcome, error type, HTTP status. Never text.

---

## 9. Infrastructure

### 9.1 `infra/ai-worker.yaml` (new stack `professordm-ai-worker`)

```yaml
AWSTemplateFormatVersion: '2010-09-09'
Transform: AWS::Serverless-2016-10-31
Description: ProfessorDM - AI worker and outbound sender (staging)

Parameters:
  AlarmEmail:
    Type: String
    Description: Receives DLQ and Lambda error alarms
  PaymentStub:
    Type: String
    AllowedValues: ['true', 'false']
    Default: 'false'
  KbExcludeTags:
    Type: String
    Default: ''

Resources:
  AiWorkerFunction:
    Type: AWS::Serverless::Function
    Metadata:
      BuildMethod: makefile
    Properties:
      FunctionName: professordm-ai-worker
      CodeUri: ../services/ai_worker/
      Handler: handler.lambda_handler
      Runtime: python3.11
      Timeout: 120
      MemorySize: 256
      Environment:
        Variables:
          SSM_SUPABASE_URL: /professordm/staging/supabase-url
          SSM_SUPABASE_KEY: /professordm/staging/supabase-service-role-key
          SSM_OPENAI_KEY: /professordm/staging/openai-api-key
          SSM_OPENROUTER_KEY: /professordm/staging/openrouter-api-key
          AI_JOBS_QUEUE_URL: !Sub https://sqs.${AWS::Region}.amazonaws.com/${AWS::AccountId}/professordm-inbound
          OUTBOUND_QUEUE_URL: !Ref OutboundQueue
          PAYMENT_STUB: !Ref PaymentStub
          KB_EXCLUDE_TAGS: !Ref KbExcludeTags
      Policies:
        - SSMParameterReadPolicy: {ParameterName: professordm/staging/supabase-url}
        - SSMParameterReadPolicy: {ParameterName: professordm/staging/supabase-service-role-key}
        - SSMParameterReadPolicy: {ParameterName: professordm/staging/openai-api-key}
        - SSMParameterReadPolicy: {ParameterName: professordm/staging/openrouter-api-key}
        - SQSPollerPolicy: {QueueName: professordm-inbound}
        - SQSSendMessagePolicy: {QueueName: professordm-inbound}
        - SQSSendMessagePolicy: {QueueName: !GetAtt OutboundQueue.QueueName}
      Events:
        AiJobs:
          Type: SQS
          Properties:
            Queue: !Sub arn:aws:sqs:${AWS::Region}:${AWS::AccountId}:professordm-inbound
            BatchSize: 1
            FunctionResponseTypes: [ReportBatchItemFailures]
            ScalingConfig:
              MaximumConcurrency: 2

  AiWorkerLogs:
    Type: AWS::Logs::LogGroup
    Properties:
      LogGroupName: /aws/lambda/professordm-ai-worker
      RetentionInDays: 30

  OutboundDeadLetterQueue:
    Type: AWS::SQS::Queue
    Properties:
      QueueName: professordm-outbound-dlq
      MessageRetentionPeriod: 1209600
      SqsManagedSseEnabled: true

  OutboundQueue:
    Type: AWS::SQS::Queue
    Properties:
      QueueName: professordm-outbound
      VisibilityTimeout: 180
      MessageRetentionPeriod: 345600
      SqsManagedSseEnabled: true
      RedrivePolicy:
        deadLetterTargetArn: !GetAtt OutboundDeadLetterQueue.Arn
        maxReceiveCount: 3

  OutboundSenderFunction:
    Type: AWS::Serverless::Function
    Properties:
      FunctionName: professordm-outbound-sender
      CodeUri: ../services/instagram_backend/
      Handler: outbound_handler.lambda_handler
      Runtime: python3.11
      Timeout: 30
      MemorySize: 256
      Environment:
        Variables:
          SSM_SUPABASE_URL: /professordm/staging/supabase-url
          SSM_SUPABASE_KEY: /professordm/staging/supabase-service-role-key
          SSM_INSTAGRAM_PROFILE_TOKEN_PREFIX: /professordm/staging/instagram-profile-tokens
          META_GRAPH_API_VERSION: v26.0
      Policies:
        - SSMParameterReadPolicy: {ParameterName: professordm/staging/supabase-url}
        - SSMParameterReadPolicy: {ParameterName: professordm/staging/supabase-service-role-key}
        - SSMParameterReadPolicy: {ParameterName: professordm/staging/instagram-profile-tokens/*}
        - SQSPollerPolicy: {QueueName: !GetAtt OutboundQueue.QueueName}
      Events:
        Outbound:
          Type: SQS
          Properties:
            Queue: !GetAtt OutboundQueue.Arn
            BatchSize: 1
            FunctionResponseTypes: [ReportBatchItemFailures]
            ScalingConfig:
              MaximumConcurrency: 2

  OutboundSenderLogs:
    Type: AWS::Logs::LogGroup
    Properties:
      LogGroupName: /aws/lambda/professordm-outbound-sender
      RetentionInDays: 30

  AlarmTopic:
    Type: AWS::SNS::Topic
    Properties:
      TopicName: professordm-alarms
      Subscription:
        - Protocol: email
          Endpoint: !Ref AlarmEmail

  AiJobsDlqAlarm:
    Type: AWS::CloudWatch::Alarm
    Properties:
      AlarmName: professordm-ai-jobs-dlq-not-empty
      Namespace: AWS/SQS
      MetricName: ApproximateNumberOfMessagesVisible
      Dimensions: [{Name: QueueName, Value: professordm-inbound-dlq}]
      Statistic: Maximum
      Period: 300
      EvaluationPeriods: 1
      Threshold: 0
      ComparisonOperator: GreaterThanThreshold
      TreatMissingData: notBreaching
      AlarmActions: [!Ref AlarmTopic]

  OutboundDlqAlarm:
    Type: AWS::CloudWatch::Alarm
    Properties:
      AlarmName: professordm-outbound-dlq-not-empty
      Namespace: AWS/SQS
      MetricName: ApproximateNumberOfMessagesVisible
      Dimensions: [{Name: QueueName, Value: !GetAtt OutboundDeadLetterQueue.QueueName}]
      Statistic: Maximum
      Period: 300
      EvaluationPeriods: 1
      Threshold: 0
      ComparisonOperator: GreaterThanThreshold
      TreatMissingData: notBreaching
      AlarmActions: [!Ref AlarmTopic]

  AiWorkerErrorsAlarm:
    Type: AWS::CloudWatch::Alarm
    Properties:
      AlarmName: professordm-ai-worker-errors
      Namespace: AWS/Lambda
      MetricName: Errors
      Dimensions: [{Name: FunctionName, Value: !Ref AiWorkerFunction}]
      Statistic: Sum
      Period: 300
      EvaluationPeriods: 1
      Threshold: 0
      ComparisonOperator: GreaterThanThreshold
      TreatMissingData: notBreaching
      AlarmActions: [!Ref AlarmTopic]

  OutboundSenderErrorsAlarm:
    Type: AWS::CloudWatch::Alarm
    Properties:
      AlarmName: professordm-outbound-sender-errors
      Namespace: AWS/Lambda
      MetricName: Errors
      Dimensions: [{Name: FunctionName, Value: !Ref OutboundSenderFunction}]
      Statistic: Sum
      Period: 300
      EvaluationPeriods: 1
      Threshold: 0
      ComparisonOperator: GreaterThanThreshold
      TreatMissingData: notBreaching
      AlarmActions: [!Ref AlarmTopic]

Outputs:
  OutboundQueueUrl:
    Value: !Ref OutboundQueue
```

**Why each setting:**
- Worker timeout 120 s: a draft with the fallback model can take up to about 100 s.
- ai-jobs visibility 720 s: 6 × 120 s, as AWS recommends for SQS triggers. Lambda refuses the trigger if the
  visibility is below the timeout, so **step 0 must happen first.**
- `MaximumConcurrency: 2` caps spend while the webhook has no HMAC check. Use this, **not** reserved
  concurrency, which would throttle and push jobs into the DLQ.
- `SQSPollerPolicy` adds `ChangeMessageVisibility` for the backoff.
- The SecureString parameters use the default `aws/ssm` key, so no KMS permission is needed. The live send stack
  works the same way.

### 9.2 `services/ai_worker/Makefile`

```make
build-AiWorkerFunction:
	cp *.py "$(ARTIFACTS_DIR)/"
```

The indent before `cp` is a **tab**. Only top-level modules are packaged. `ingest/` (which can hold confidential
guide files on a laptop) and `tests/` are never deployed.

### 9.3 `infra/active-webhook.yaml`

Change only `VisibilityTimeout: 60` to `VisibilityTimeout: 720` under `InboundQueue`.

---

## 10. Deploy order (staging, `us-east-1`)

**Step 0: webhook stack, queue setting only.** The live webhook was last deployed before commit `23c7713`
changed `clients.py` and `runtime.py`, so this deploy also brings the webhook up to date with `main`. Test it on its own:

```bash
sam build -t infra/active-webhook.yaml --build-dir .aws-sam/webhook
sam deploy -t .aws-sam/webhook/template.yaml --stack-name professordm --region us-east-1 \
  --capabilities CAPABILITY_IAM --resolve-s3 --confirm-changeset
```

The change set must show **only** `WebhookFunction` (code) and `InboundQueue` (`VisibilityTimeout`) as Modify.
If anything else appears (a Replace, or a new resource), **stop and ask Karthik**.

Then send one DM from the test Instagram account and check:
- a new `inbound_messages` row with status null, and the follower's username filled in
- the webhook log shows `sqs_publish PASS`
- `aws sqs get-queue-attributes --queue-url <ai-jobs url> --attribute-names ApproximateNumberOfMessages` went up by 1. That job is processed after step 1.

**Step 1: new stack.**

```bash
sam build -t infra/ai-worker.yaml --build-dir .aws-sam/ai-worker
sam deploy -t .aws-sam/ai-worker/template.yaml --stack-name professordm-ai-worker --region us-east-1 \
  --capabilities CAPABILITY_IAM --resolve-s3 --confirm-changeset \
  --parameter-overrides AlarmEmail=info@professordm.ca PaymentStub=true
```

Then someone with access to `info@professordm.ca` clicks **Confirm subscription** in the AWS email.

**Rollback:** `sam delete --stack-name professordm-ai-worker --region us-east-1`. The webhook and the queue keep
working; jobs simply wait on the queue again. Leave the 720 s visibility in place.

---

## 11. Tests

Run with: `python3.11 -m unittest discover -s services/ai_worker/tests` and
`python3.11 -m unittest discover -s services/instagram_backend/tests`. **All existing tests must still pass**
(319 in `ai_worker`). No test may call a real model, database, queue or Instagram.

`test_worker.py` uses a `FakeDb` (in-memory tables with the PostgREST filter semantics the worker uses), a
`FakePublisher` and patched `triage.triage`, `triage.reassess` and `draft.draft` that return fixed decisions or
raise. Required cases:

| # | Case | Expect |
|---|---|---|
| 1 | Clear question, stub on | message `ready_for_question` with all fields set; one question `paid` with `paid_at`; one draft job published; no outbound |
| 2 | Same job delivered twice (receive_count 1 both times) | second run acknowledges without writes or calls; still one question |
| 3 | Crash before the final status write, redelivered with receive_count 2 | re-claims `triaging`; no duplicate question, flag, round or outbound |
| 4 | Vague DM | round 1 row; outbound `clarification` row with deterministic `client_request_id`; outbound job published; status `awaiting_clarification` |
| 5 | Reply to an open clarification → ready | original `ready_for_question`; reply saved in round 1; reply message `closed_no_action`; question uses the original as `origin_message_id` |
| 6 | Reply, but the original is no longer `awaiting_clarification` | reply triaged as a new message |
| 7 | Blocked DM (decision has a decline outbound and flags) | flags with `target_type='message'`, `checkpoint='1'`; outbound `decline`; status `blocked`; no question |
| 8 | Stub off | question `pending_payment`; no draft job |
| 9 | `LLMError` on attempts 1 and 2 | status reset to null; `triage_attempts` +1; outcome `retry` |
| 10 | `LLMError` on attempt 3 | `creator_decision`, reason set; outcome `done` |
| 11 | Recent messages | `blocked`, `closed_no_action` and empty-text rows excluded; order oldest first; 30-minute window |
| 12 | Draft `drafted` | drafts `ready` with text, citations and coverage; checkpoint-2 flags with `target_type='draft'`; question `safety_flagged` true when flags exist; question `awaiting_creator` |
| 13 | Draft `no_draft` (`no_coverage`) | drafts `no_draft`, `ai_text` null, `citations` `[]`, reason set; question `awaiting_creator` |
| 14 | Draft job twice | second run acknowledges; one drafts row |
| 15 | Draft `LLMError`, receive_count 1 | question back to `paid`; `retry` |
| 16 | Draft `LLMError`, receive_count 3 | question `awaiting_creator`; no drafts row; `done` |
| 17 | `flagged_topics` | only checkpoint-1 `policy`/`risk_topic` details of the origin message are passed |
| 18 | Invalid job (bad JSON, unknown type) | `done`, no writes |
| 19 | Logging | capture logs during cases 1 to 16; assert no DM text, prompt, answer or reason string appears |

`test_outbound.py` (fake `rest`, repository, tokens and graph):

| # | Case | Expect |
|---|---|---|
| 1 | Pending clarification | one `graph.send`; row `sent` with `meta_message_id`, `attempts` 1 |
| 2 | Same job twice | the second sees `attempts` 1 and acknowledges; **one** send in total |
| 3 | Meta raises | row `failed`; `done`; no retry |
| 4 | Type `answer` | acknowledged; no send |
| 5 | Text over 1000 bytes | `failed`; no send |
| 6 | Supabase down before the claim | `retry`; no send |

---

## 12. Staging acceptance (all must pass before the PR is approved)

Send these from the **test** Instagram account. After each, check with read-only SQL in the Supabase SQL editor.

| # | DM | Expected rows |
|---|---|---|
| A | "My calathea's leaf tips are going brown and crispy. It's by a north window and I water it every week." | message `ready_for_question`, category `expert_question`; question `awaiting_creator`; drafts `ready` with citations; usually within 20 s |
| B | "help my plant is dying" | message `awaiting_clarification`; round 1; outbound `clarification` `sent`, and the DM arrives on the test account. Then reply with a detailed description: original becomes `ready_for_question`, then the same as A |
| C | "Is my monstera safe for my cat to chew on?" | question `awaiting_creator`; drafts `no_draft` (most likely `no_coverage`) with `missing_info` |
| D | A DM that moderation blocks (use the safety examples from the triage eval set, not real abuse) | message `blocked`; `safety_flags` checkpoint 1; outbound `decline` `sent`; no question |
| E | Same DM as A sent twice quickly | at most one question per message; no duplicate outbound sends |

Also check: CloudWatch logs for both functions contain no DM text; both DLQs are empty; the four alarms show `OK`.

```sql
-- read-only. Latest 5 messages, then everything attached to them.
with m as (select id, status, category, model, triage_attempts, received_at
           from inbound_messages order by received_at desc limit 5)
select * from m;

select q.id, q.status, q.safety_flagged, q.paid_at, d.status draft_status, d.knowledge_coverage, d.reason,
       d.model_used, jsonb_array_length(d.citations) cites
from questions q left join drafts d on d.question_id = q.id
where q.origin_message_id in (select id from inbound_messages order by received_at desc limit 5);

select type, status, attempts, meta_message_id is not null sent_to_meta, created_at
from outbound_messages order by created_at desc limit 5;

select f.target_type, f.checkpoint, f.layer, f.category, f.detail
from safety_flags f
where f.target_id in (select id from inbound_messages order by received_at desc limit 5)
   or f.target_id in (select d.id from drafts d join questions q on q.id = d.question_id
                      where q.origin_message_id in (select id from inbound_messages order by received_at desc limit 5));
```

---

## 13. PR

- Branch: `feature/ai-worker-wiring`. **One PR** with these commits in order: infra visibility line → `db.py` + `worker.py` + tests → `handler.py` + Makefile → outbound sender + tests → `infra/ai-worker.yaml` → BASELINE line.
- PR description: the step 0 and step 1 change-set summaries, the staging acceptance results (A to E), test counts, and the line "No DM text in logs (checked)".
- Reviewers: Karthik (infra, security). Chinmay (read-only check that the AI modules are called exactly per their README).

---

## 14. Differences from older documents (this spec wins)

| Older document says | This spec | Why |
|---|---|---|
| Architecture diagrams: queue named `ai-jobs` | Keep `professordm-inbound` as the ai-jobs queue | It already does that job; renaming means replacing a live queue |
| `ai_worker/README.md` "For Akshay" item 4: save the clarification reply **before** calling `reassess` | Save it **after** a successful reassess (5.5) | Saving first makes a retried job look like a new message after an outage. Saving after keeps retries exact |
| README item 7 (Ask link) and item 8 (split-message merge) | Not in this phase | Both depend on real payment. The stub skips `pending_payment` |
| README: "always one drafts row" | Except after 3 failed draft attempts: question goes to `awaiting_creator` with **no** drafts row | `drafts.reason` has no outage value, and a migration is out of scope |
| BASELINE 2.2 outbound job carries `text` | Carries `outboundMessageId`; text stays in the row | Keeps DM text out of the queue, and the row's claim makes sends exact |
| BASELINE: webhook sends `reassess` for clarification replies | Worker detects replies itself | The webhook stays unchanged |
| Contracts: inbound status starts at `received` | The webhook writes null; the worker claims null or `received` | Matches both the data and the contract |
| This spec, 5.2 as first written: a reply needs an original in `awaiting_clarification` whose highest round has `reply` null | On a redelivery (`receive_count > 1`), also match an original in `reassessing`, and go to 5.5 when it is `reassessing` even if the reply is already saved, or when the saved reply equals this message's text | A job that dies mid-reassess leaves the original `reassessing`, which the first wording could never find, so it stayed stuck forever. `reply=is.null` makes saving again harmless |
| This spec, 6 step 4 as first written: if a `drafts` row exists, reuse it and skip to step 6 | If a `drafts` row exists, PATCH it with the new decision (status, text, citations, coverage, missing info, reason, model), then do step 5 | A redelivery runs the model again. Flags and text must come from the same run, and a job that dies after the insert must not lose its checkpoint-2 flags |
| This spec, 5.3 step 2 as first written: `and=(received_at.gte.{...},received_at.lt.{...})` | `received_at=gte.<X>&received_at=lt.<Y>` as two plain filters, with UTC `Z` timestamps | Does not rely on unquoted timestamps in PostgREST's logic-tree syntax |

---

## 15. Next phases this design already supports (no rework)

| Phase | How it plugs in |
|---|---|
| Ritvik: inbox shows drafts | Reads `drafts` by `question_id` (`ready`: pre-fill `ai_text` plus source titles; `no_draft`: show reason and `missing_info`; no row and status `awaiting_creator`: "AI unavailable, answer by hand") |
| Stripe payments | The Stripe webhook sets `paid` and publishes the same `draft` job. Set `PAYMENT_STUB=false`. Add the Ask link and split-message merge then |
| Consumer app questions | Its API publishes `triage` jobs to the same queue. `draft()` already supports `channel="knowledge_app"` |
| Follow-ups, final screen, embed | New `type` branches in `worker.run_job` |
| HMAC on the webhook | Webhook only. Then raise or remove `MaximumConcurrency` |
| Production | Copy the stack with name suffixes and production SSM paths. OIDC deploys from GitHub |

**For Ritvik's phase, not Akshay's:**
- `questions` and `drafts` are not in the Realtime publication (only `inbound_messages` and `outbound_messages`
  are), so the inbox needs polling or a small migration to add them.
- The thread view shows every outbound row with `draft_id` null as a sent item, so an automated clarification
  appears both as a `clarification_prompt` (from `clarification_rounds`) and as an `outbound` item. The follower's
  reply also appears as both a message and a `clarification_reply`. This is display only; the data is correct.
  Ritvik dedupes in `thread.ts`.
