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

The sender API stack and Creator Workspace have not been deployed. The Graph API version and staging Instagram account/Vault link are still pending. Live `ig_accounts` currently has zero rows. The authenticated creator RLS and Realtime experience still need an end-to-end test with a real creator session and linked Instagram test account.
