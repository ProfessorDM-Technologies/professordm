# October 16 staging rollout

Account `939603205947`, region `us-east-1`, profile `professordm-staging`, Supabase project `lejzezabvfhnfovkyxsx`. The Meta callback stays on REST API `ycmf4156e3`, `GET/POST /webhook`, Lambda `professordm-webhook`.

## Gates before deployment

1. Confirm the staging SSM `meta-app-secret` and `meta-verify-token` match the Meta app currently calling `/webhook`. Never paste their values into a ticket or command history.
2. Confirm the Meta Graph API version and link the staging Instagram account in `ig_accounts`, with `vault_token_id` pointing to a Vault secret. Keep the token in Vault.
3. Apply migrations `20261014_006_oct16_realtime_publication.sql` and `20261014_007_meta_page_token_rpc.sql` in the staging Supabase SQL Editor. Run `docs/oct16-staging-verification.sql`; both tables must appear, RLS must remain enabled, and only `service_role` may execute the Vault function.
4. Run Python tests and Creator Workspace lint, typecheck, tests, and build. Review `git diff --check` and a secret scan.

## AWS rollout

The active webhook belongs to the existing `professordm` SAM stack. `infra/active-webhook.yaml` is copied from that stack's original template, with its code path updated and four staging SSM parameter names. It preserves the existing REST API routes and queue resources. Deploy it through the stack, not a direct Lambda code/config update, to avoid CloudFormation drift. Create and inspect a change set first; stop if it proposes replacement of the API, queue, or Lambda.

The sender is a separate SAM stack in `infra/oct16-send-api.yaml`. Its output `SendUrl` is the server-side `INSTAGRAM_SEND_API_URL` for Creator Workspace. The sender validates the creator JWT in Lambda; the API Gateway route itself is public.

```sh
export AWS_PROFILE=professordm-staging AWS_REGION=us-east-1
aws sts get-caller-identity --query Account --output text
python3 -m unittest discover -s services/instagram_backend/tests -v
sam validate --template-file infra/active-webhook.yaml
sam validate --template-file infra/oct16-send-api.yaml
sam build --template-file infra/active-webhook.yaml --build-dir .aws-sam/webhook-build
sam build --template-file infra/oct16-send-api.yaml --build-dir .aws-sam/send-build
```

Deploy only after the gates pass. Supply the approved `GraphApiVersion` parameter to the sender stack. Review each CloudFormation change set before execution, preserving `ycmf4156e3` and the Meta callback URL. Set the Creator Workspace deployment's server-side `INSTAGRAM_SEND_API_URL` to `SendUrl`, then deploy that application through its Vercel staging process.

## Live checks

Send a test Instagram DM, then verify the active webhook's invocation, one `inbound_messages.mid` row, its `ig_followers` owner, and a triage message on `professordm-inbound`. The queue has no consumer for this milestone. Using a real authenticated creator session, verify own-row visibility, cross-creator isolation, Realtime delivery, and display in `/incoming` and `/inbox`. Submit a manual reply in the thread, verify one `outbound_messages` row for its `client_request_id`, a `sent` status and Meta message ID, and receipt by the Instagram follower. Use a safe failing test to verify `failed` state without exposing provider or Vault secrets.

Meta can retry webhooks, and SQS is an at-least-once queue. The inbound row is unique by `mid`; duplicate deliveries may publish the same stable `triage:<message_id>` job identity again. There is deliberately no SQS consumer. Outbound reservations prevent duplicate Meta calls for the same `client_request_id`. If Meta succeeds but the final database update fails, the row may remain `pending` and requires manual reconciliation; automatic retries are disabled to avoid duplicate sends.

## Staging rollout status, October 14

The existing `professordm` CloudFormation stack was updated from this branch after a change-set review. The REST API resource was modified without replacement, and its parsed routes remained `GET /webhook` and `POST /webhook`. The active callback remains REST API `ycmf4156e3` and Lambda `professordm-webhook`; the queue remains `professordm-inbound`.

Deployed smoke checks: valid verification challenge returned HTTP 200 with the expected challenge, invalid verification token returned 403, invalid POST signature returned 401, and a correctly signed synthetic POST for an unconnected recipient returned 200 with no inbound row. Recent Lambda logs did not contain the synthetic DM text, signature header, or the checked SSM secret values. `professordm-inbound` has no Lambda event source mapping. These checks do not prove delivery of a real Meta DM.

The sender stack `professordm-staging-oct16-send` is deployed in `CREATE_COMPLETE`. Its REST API ID is `kch00hbznd`, and `POST /Staging/api/send` is available at `https://kch00hbznd.execute-api.us-east-1.amazonaws.com/Staging/api/send`. Its Lambda is `professordm-staging-instagram-send`, with Graph API version `v26.0`. A malformed POST returned HTTP 400, and a structurally valid unauthenticated POST returned HTTP 401; neither check sent a Meta message.

The staging Facebook Page ID is `1358275557370847`, and the Instagram Business Account ID is `17841479724216495`. The Instagram account is now linked to the staging creator in `ig_accounts` (row `f4f57c1c-6317-45c2-8b91-381f0fa58472`) with a Vault secret UUID; the backend-only RPC returned a nonempty token without displaying it. The user reports that Creator Workspace has been redeployed with `INSTAGRAM_SEND_API_URL`; its staging URL and behavior have not yet been independently checked.

A read-only Graph API check accepted the Vault token but `GET /v26.0/me?fields=id` returned asset ID `122099962713511526`, not the expected Facebook Page ID. `GET /v26.0/me/accounts?fields=id` returned no Pages, and a query for the expected Page returned Graph error code 100. Verify that the Vault secret holds a Page access token for Page `1358275557370847` and its linked Instagram Business Account before sending a reply. A real inbound DM, authenticated creator visibility, Realtime delivery, and a manual reply still need end-to-end tests.

With the account linked, a signed synthetic text DM sent to the existing `/Prod/webhook` route returned HTTP 200. Replaying the exact payload returned HTTP 200 again. The synthetic `mid` has exactly one `inbound_messages` row, its follower belongs to the staging creator and has `last_inbound_at`, and the `professordm-inbound` visible message count rose from 38 to 40. Two SQS events for a replay are expected because the queue is at least once and has no consumer. No outbound Meta message was sent in this check.

The first reported real DM was sent near 12:08 PM MST on October 14. No inbound row with its text appeared after that time, and the SQS visible count stayed at 40. The active Lambda had invocations after the reported time, while the `Prod` API Gateway metrics recorded mostly 4XX responses; neither Lambda nor API Gateway had request-level status/method logs to tie one response to that DM. The user later supplied `https://professordm-creator-workspace.vercel.app`; `/login` is reachable and `/incoming` redirects to login. An authenticated Creator Workspace session has not yet been observed.

For the next DM, the staging webhook Lambda was redeployed through the existing `professordm` stack with safe diagnostic logs recording only request method, response status, and signed message candidate count. The reviewed change set modified Lambda code without replacement; the processed API Gateway body was identical to the existing one. After deployment, a valid verification GET logged status 200 and a deliberately invalid POST signature logged status 401. The Meta callback route and resource IDs are unchanged.

A second real DM was reported sent near 12:36 PM MST. Between 19:36:19 and 19:36:28 UTC, the active `/Prod/webhook` Lambda logged eight POST requests, each with status 401. In this handler, POST 401 is returned only when the `X-Hub-Signature-256` HMAC check fails. No signed message candidate log appeared, no follower had `last_inbound_at` updated after 12:35 PM MST, no inbound row appeared, and the visible SQS queue count remained 40. The first observed failing boundary is signature verification, before creator/account resolution. A signed synthetic POST previously succeeded through the same route, so request handling and HMAC code work for a correctly signed request; the live delivery's signature header and signing app secret still need to be checked in Meta without exposing their values.

The user triggered Meta's built-in `messages` sample near 12:41 PM MST. The active Lambda logged four POST 401 responses between 19:40 and 19:41 UTC, with no signed message candidate log. A further staging-only diagnostic update added Boolean logging for signature header presence and format, without logging header values, secrets, or payloads. Its reviewed change set modified only Lambda code; the processed API Gateway body was unchanged. Subsequent POSTs at 19:43:15 and 19:44:22 UTC had both `X-Hub-Signature-256` (correct `sha256=` length) and the legacy signature header present, `isBase64Encoded=false`, and still returned 401. These requests occurred during the sample retry window, but the existing API Gateway configuration does not log a source or request identifier, so their exact origin cannot be proven from AWS logs alone. A separate correctly signed diagnostic POST after the update returned 200 and logged one message candidate. No follower or inbound row appeared after 12:40 PM MST, and the SQS visible count remained 40. The failure is at HMAC verification, not Instagram DM payload parsing; the cause of the HMAC mismatch still needs confirmation against the Meta app and its signing secret.
