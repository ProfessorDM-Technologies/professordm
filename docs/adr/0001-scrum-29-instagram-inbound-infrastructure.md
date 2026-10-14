# SCRUM-29: Instagram inbound infrastructure

The first inbound slice exposes only `POST /webhooks/instagram` through API Gateway HTTP API to the `ig-webhook` Lambda. The Lambda verifies Meta's raw-body signature, writes to the existing Supabase tables, then sends a `triage` job to `ai-jobs`. The queue has a dead-letter queue and a redrive limit of three receives for the future worker.

`infra/template.yaml` defines only this Lambda, route, queue, DLQ, and send permission. The Lambda reads `META_APP_SECRET`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, and `AI_JOBS_QUEUE_URL` from environment variables. Secret values must be sourced from AWS SSM SecureString by the deployment process and passed as no-echo stack parameters; the template contains names and references only. Build the pnpm service bundle before `sam build` or deployment.

No Supabase schema or migration changes are part of SCRUM-29. A retry after database success and SQS failure reuses `inbound_messages.mid`. Triage uses `JobEnvelope.id = triage:<inbound_messages.id>` so retries keep the same job identity. Without an outbox, retries can still enqueue more than one SQS message; the future worker must honor the shared contract's idempotency requirement on `JobEnvelope.id`.
