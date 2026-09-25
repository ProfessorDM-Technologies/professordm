# ProfessorDM V1 Requirements + Architecture Baseline

Milestone: **Sep 25, 2026**. Accountable: Karthik + leads (Roles doc section 6).
The Roles doc says this milestone covers system context, data flows, interface contracts, security and privacy assumptions, acceptance criteria and test strategy. The proposal adds data retention.

| Required item | Where |
|---|---|
| System context | Diagram 00 |
| Data flows | Diagrams 02, 02b, 03 to 06 |
| Data model | Diagram 11 |
| Interface contracts | Section 2 below, then `packages/contracts` in code |
| Security + privacy assumptions | Section 3 |
| Acceptance criteria | Section 4 |
| Test strategy | Section 5 |
| Data retention | Section 6 |

## 1. Scope

**In V1:** Instagram only (Sweetlife Flora). One creator. Creator Workspace. Consumer App (Ask page + Ask Sweetlife Flora Knowledge App). Stripe test mode, plus a limited live trial if approved.

**Deferred (proposal section 9):** TikTok and other platforms, native apps, large-scale multi-creator onboarding, advanced analytics, multilingual support, specialized diagnostic AI, production-grade treasury/escrow/payouts, high availability and multi-region. Also deferred: the creator SaaS subscription and Stripe Connect.

## 2. Interface contracts (owners agree, Karthik keeps them consistent)

### 2.1 Status model (single enum set in `packages/contracts`)

**inbound_messages.status** (Akshay + Chinmay)
`received > triaging > closed_no_action | blocked | service_routed | awaiting_clarification > reassessing > ready_for_question | creator_decision`

**questions.status** (Akshay routing, Ritvik displays, Arun displays)
`pending_payment > paid > drafting > awaiting_creator (flag_review first if safety_flagged) > approved > final_screening > (professordm_review) > delivering > delivered > accepted | closed`
Side states: `declined_refunded`, `refund_requested`, `refunded`, `refund_denied`, `delivery_failed`.
Money is **pending** until `hold_ends_at` (delivered_at + 3 days, start point to confirm with Kristin) and **available** after that, unless refunded. The hourly scheduler sends the day-2 survey, auto-accepts at day 3, queues the knowledge embed and triggers automatic payouts (weekly Friday, or 30 days for On Demand).

**followups.status**: `received > drafting > awaiting_creator > approved > delivered | off_topic_flagged`

**outbound_messages.delivery_mode**: `standard | human_agent | fallback_email`

### 2.2 SQS payloads

Every message carries: `{ v: 1, type, id, creatorId, traceId, createdAt }`

| Queue | type | Extra fields | Producer | Consumer |
|---|---|---|---|---|
| ai-jobs | triage | messageId | ig-webhook, api (app ask) | ai-worker |
| ai-jobs | reassess | messageId | ig-webhook | ai-worker |
| ai-jobs | draft | questionId | stripe-webhook | ai-worker |
| ai-jobs | followup | questionId, followupId | ig-webhook, api | ai-worker |
| ai-jobs | final_screen | draftId | api | ai-worker |
| ai-jobs | embed | questionId | scheduler (hold ended, not refunded) | ai-worker |
| ai-jobs | kb_safety_review | creatorId | scheduler (weekly) | ai-worker |
| ai-jobs | ingest | docId | api | ai-worker |
| outbound | ask_link, clarification, confirmation, answer, followup, rating_prompt, survey, decline, status | recipientFollowerId, draftId?, text | ai-worker, api | sender |

Every consumer is idempotent on `id`. After 3 failed attempts a job goes to the DLQ and an alert fires.

### 2.3 api routes (API Gateway, Supabase JWT, role checked on every route)

| Route | Role | Built with |
|---|---|---|
| POST /messages/:id/override | creator | Ritvik |
| POST /drafts/:id/approve  (server re-checks edit + tags) | creator | Ritvik |
| POST /followups/:id/approve | creator | Ritvik |
| POST /questions/:id/decline | creator | Ritvik |
| POST /refunds/:id/approve, /deny | creator | Ritvik |
| POST /moderation/:flagId/creator-review | creator | Ritvik |
| POST /moderation/:flagId/decision (flagged answers) | admin | Ritvik |
| PUT /creator/settings, POST /knowledge, POST /payouts | creator | Ritvik |
| GET, PUT /ask/:token | public, signed token | Arun |
| POST /search, /entries/:id/view | consumer | Arun |
| POST /questions, /questions/:id/followups, /questions/:id/accept, /questions/:id/refund-request | consumer | Arun |
| POST /webhooks/instagram, /webhooks/stripe | signature only | Akshay |

Reads (lists, detail, bank) go straight from the apps to Supabase with RLS. Live updates use Realtime.

### 2.4 AI output contract (Chinmay)

`classify` returns `{ category, confidence, reason, promptVersion, model }`.
`draft` returns `{ text, citations: [{ kind: knowledge|web, ref }], knowledgeCoverage: high|partial|none, usedWebSearch, flags: [], promptVersion, model }`.

## 3. Security + privacy assumptions

1. Every production account is owned by a ProfessorDM company email. None sits only under a student or ASU email.
2. No secrets in code. Secrets live in Vercel env vars, AWS SSM SecureString, GitHub Actions secrets (with OIDC to AWS) and Supabase Vault for the Meta token. If a secret leaks, rotate it immediately.
3. RLS is on for every table and denies by default. The service role key is only used inside Lambdas.
4. Roles are creator, admin and consumer. Admin is ProfessorDM staff only.
5. Meta webhooks are verified with HMAC SHA-256. Stripe webhooks are verified by signature. Both are processed idempotently.
6. Storage buckets are private and served through short-lived signed URLs.
7. Sentry scrubs PII before any real DM content flows through. DM text never goes into error logs or Amplitude.
8. Q+A is anonymized (handle, names, contact details removed) before it enters knowledge_entries.
9. HITL is enforced in the api, not just the UI. No AI text is sent to a follower without creator approval, except clarification prompts and system messages (Ask link, confirmation, status).
10. Kristin signs off the blocked-category list for the domain rules before live DMs.
11. Trial participants give consent before the April trial (Maximo + Nova).

## 4. Acceptance criteria by milestone (Roles doc section 6)

| Date | Done means |
|---|---|
| Oct 16 | Test IG DM hits ig-webhook on staging, gets verified, stored and queued. A test DM goes out from sender. Both app shells deploy. Auth works for all 3 roles. |
| Oct 30 | Triage classifies the golden set, meets the agreed accuracy bar and records a confusion matrix. Clarification round trip works. Seed docs are embedded. Retrieval returns relevant entries. A grounded draft is produced. Safety checkpoints 1 and 2 are running. |
| Nov 13 | Live path on staging: IG DM > triage > question in Creator Inbox > draft > creator edits and approves > answer DM delivered > Q+A embedded. Moderation path is demonstrable. Payment is stubbed. |
| Dec 1 | Stable alpha, E2E test for the Nov 13 path, open defect list, Spring backlog. |
| Feb 12 | Stripe test flow end to end, follow-ups, refunds, Knowledge App search + gating + Ask, moderation queue, logging. |
| Mar 5 | Security, privacy, performance and resilience review done. Restore drill done. Trial scripts ready. |
| Mar 26 | Acceptance tests pass on all critical workflows. Production environment ready. Known limitations documented. |

## 5. Test strategy

| Layer | Tool | Owner |
|---|---|---|
| Unit | Vitest | Each lead for their workstream |
| Contract | Zod schemas in `packages/contracts`, tested in CI | Karthik + producers/consumers |
| AI eval | golden sets, accuracy, retrieval relevance, grounding, safety red-team | Chinmay, gates with Karthik |
| E2E | Playwright on flows 02 and 02b against staging | Karthik |
| Sponsor acceptance | Demo on staging at each milestone | Nova records sign-off |
| Trial | Scenarios + observation | Maximo |

Release gate: CI green, lead approval, eval not below baseline, E2E green on staging.

## 6. Data retention (proposal: minimization + retention)

| Data | Keep | Then |
|---|---|---|
| Inbound DMs classified social or spam | 30 days | delete text, keep category counts |
| Unpaid questions and clarifications | 90 days | delete |
| Paid questions, answers, follow-ups | life of the account | delete on creator or follower request |
| Images | same as the parent record | delete with it |
| Knowledge entries | until the creator deletes them | anonymized, so not personal data |
| Payments + ledger | 7 years (tax) | kept, no DM content inside |
| audit_log | 2 years | archive |
| Sentry | Sentry free tier default | PII scrubbed |

Nova takes these numbers to Kristin as the proposed policy. They go into the privacy policy before the trial.
