# Manual Instagram replies — staging

## Source of truth and scope

Branch `outbound-instagram-replies` starts at main `cb6933049e819f4d1d0d652754f193a8dc455cec` (merged Scrum-96). The working inbound code resolves recipient `ig_accounts.ig_user_id`, follower `ig_scoped_id`, and creator ownership through `creators.profile_id`. It uses `SsmProfileTokens`, not the legacy sender's Vault token. Outbound now reuses that provider and the existing Instagram Login credential at `/professordm/staging/instagram-profile-tokens/17841479724216495`.

This follows the user's correction to use working inbound as the credential architecture source of truth. No token is copied, rotated, or written. Vault and its RPC are unchanged. No schema migration is needed. The active inbound Lambda, callback, subscriptions, enrichment, and queue are not deployed or changed.

The Instagram User token needs `instagram_business_basic` and `instagram_business_manage_messages`. It must belong to receiving account `17841479724216495`; read-only `GET https://graph.instagram.com/v26.0/me?fields=user_id` checks this before sending. The app-scoped `id` is not the webhook account ID. A read-only profile request with the existing provider returned sender `2234200840491090`, username `akshayvoora`, before deployment.

## Existing infrastructure reused

- AWS account `939603205947`, profile `professordm-staging`, region `us-east-1`.
- Stack `professordm-staging-oct16-send`, Lambda `professordm-staging-instagram-send`.
- REST API `kch00hbznd`, `POST /api/send`, Lambda proxy integration.
- Server-side `INSTAGRAM_SEND_API_URL`: `https://kch00hbznd.execute-api.us-east-1.amazonaws.com/Staging/api/send`.
- Supabase project `lejzezabvfhnfovkyxsx`; URL/service key read through existing SSM parameters.
- Creator Workspace `https://professordm-creator-workspace.vercel.app` (requires deployment of this branch for updated UI behavior).

Only the sender stack is deployed. Its existing execution role receives SAM's `SSMParameterReadPolicy` for the existing staging Instagram credential prefix. There are no new token parameters, APIs, queues, or database objects. Source analysis can independently audit SDK calls with:

```sh
uvx iam-policy-autopilot@latest generate-policies \
  /private/tmp/professordm-outbound/services/instagram_backend/runtime.py \
  /private/tmp/professordm-outbound/services/instagram_backend/clients.py \
  --region us-east-1 --account 939603205947 --service-hints ssm sqs --pretty
```

This is an optional source audit, not a policy upload; deployment uses the existing SAM policy template.

## Live database inspection

The user ran `docs/outbound-staging-inspection.sql` in staging SQL Editor before implementation and supplied the catalog result. It confirms:

- Existing outbound columns include creator, inbound, follower, text, client request ID, created time, status, attempts, delivery mode, and Meta message ID.
- `outbound_messages_client_request_id_key` is a UNIQUE index on `client_request_id`; reservation is an atomic INSERT, not check-then-insert.
- Existing FK and direct-answer constraints match the request contract.
- RLS is enabled on inbound and outbound. Creator SELECT and direct-answer INSERT policies remain unchanged; service-role backend authorization explicitly checks the authenticated creator owns the follower.
- Both tables are published in `supabase_realtime`.
- The existing Vault RPC is executable only by service_role; outbound does not need it under the corrected architecture.

## Request, send, and status behavior

The browser submits only inbound message ID, reply text, and client request UUID. The Next server action forwards the authenticated Supabase session JWT to the existing API. Lambda validates it with Supabase Auth, resolves ownership, and reserves an `answer`, `standard`, `pending`, attempts=0 row. Missing or ambiguous accounts fail before any Meta call.

The reservation's unique UUID is bound to creator, inbound message, and text. Sequential or concurrent reuse returns the existing status without another Meta POST. A mismatching request returns 409. Browser-supplied creator/follower/account IDs are not trusted.

After credential and account validation, attempts=1 is recorded before:

```text
POST https://graph.instagram.com/v26.0/{ig_user_id}/messages
recipient.id = ig_followers.ig_scoped_id
message.text = validated manual reply
```

The provider response must include the exact recipient and a nonempty message ID. Success stores `sent` plus `meta_message_id`. Failure stores `failed` with attempts, and logs only stage, error class, HTTP status, Meta code/type. The live schema has no safe error-detail column; no migration is added just for that. No token, JWT, reply text, or raw provider error enters logs or browser errors.

There is no automatic retry of the Meta POST. Only the final DB PATCH is retried. An ambiguous provider timeout or a delivered message whose status cannot be saved must be manually reconciled before composing a fresh reply. Reusing the same UUID never repeats the send. A failed UUID is also not retried. Refreshing the page creates a new composition ID; check Instagram first after uncertain delivery.

The UI distinguishes `pending` from `sent`, refreshes DB-backed conversation data, and keeps the same UUID for status checks. Text is limited to 999 characters and 1,000 UTF-8 bytes. Instagram messaging windows and account permissions are enforced by Meta; a fresh inbound DM is required for the controlled live test.

## Verification

Before deployment:

- 47 Python backend tests pass, including inbound regression, valid send, authentication, ownership, missing message, invalid text/IDs, sequential/concurrent duplicate reservation, failed Meta no retry, credential failure, token identity mismatch, and status persistence failure/retry.
- 30 Creator Workspace tests pass; ESLint, typecheck, and production build pass.
- SAM validation with cfn-lint passes for `infra/oct16-send-api.yaml`.

Live acceptance is pending. A user must deploy this branch to the existing demo Vercel app, send a fresh Instagram DM, then submit one unique manual reply from the authenticated conversation. Record outbound row ID, client request ID, Meta message ID, follower/account ID, final status, UI display, and confirmation of exactly one received Instagram reply. No PR or merge until requested.

## Meta references

- [Instagram Login messaging API](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/messaging-api): Instagram User token, permissions, versioned Instagram host, send contract and response.
- [Instagram user profile API](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/messaging-api/user-profile): supported sender profile lookup used by inbound.
