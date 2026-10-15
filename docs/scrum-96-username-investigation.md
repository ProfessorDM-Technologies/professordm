# Scrum-96: map inbound Instagram senders to usernames

Status: the Instagram Login profile lookup has passed read-only validation for
both known real followers. The implementation has 33 passing backend tests and
is deployed to staging. A fresh real DM remains the completion gate.

## Product requirement

Starting with a real inbound webhook's sender IGSID, fill
`public.ig_followers.username` with the actual username returned by a supported
Meta API. Enrich new followers and existing followers whose username is NULL;
skip accounts with a populated username. Enrichment failure must leave inbound
persistence, the stable MID identity, SQS publishing, and HTTP 200 intact.

## Supported Meta v26.0 options

| Option | Supported response and safe mapping | Token requirements | Staging evidence |
| --- | --- | --- | --- |
| Instagram Login User Profile API: `GET https://graph.instagram.com/v26.0/{IGSID}?fields=id,username,name` | Direct lookup of the exact sender IGSID from a messaging webhook. Returns `username`; the implementation also verifies the returned sender ID. | Instagram User access token for the receiving professional account; `instagram_business_basic` and `instagram_business_manage_messages`. The sender must have granted messaging consent, such as by sending a DM. | PASS with the new Instagram User candidate for both known real senders. Facebook tokens are rejected by this host with code 190. |
| Facebook Login User Profile API: `GET https://graph.facebook.com/v26.0/{IGSID}?fields=username,name` | Direct lookup of the sender IGSID. Returns `username`. | Page access token for the linked Page; Meta's current profile guide lists `instagram_basic`, `instagram_manage_messages`, `pages_manage_metadata`, `pages_read_engagement`, `pages_show_list`, and a Page MODERATE task. | Both available tokens return HTTP 400 / OAuthException code 100 for the two real sender IGSIDs. |
| Conversation participants: find the conversation using `/{receiving-account}/conversations?user_id={IGSID}`, then read `participants` | Only accept a participant whose `id` exactly matches the webhook sender; never choose the first participant or the business's username. | Token and permissions for the selected Instagram Login or Facebook Login messaging API. This does not bypass messaging authorization. | Facebook-host Instagram conversation queries with both tokens return HTTP 400 / code 3: the app lacks capability for the call. Page-hosted conversation queries cannot access the expected Page. |
| Message sender: `GET /{webhook-MID}?fields=id,from,to` | Require the returned message ID, `from.id`, and receiving account in `to` to match the webhook before accepting `from.username`. No message content is needed. | Token and permissions for the selected messaging API. Meta limits message detail reads to the 20 most recent messages in a conversation. | Reads of the two most recent real inbound MIDs with both Facebook tokens return HTTP 500 / code 1: an unknown error occurred. |

The Instagram Login profile lookup is the selected approach. It uses the exact
sender IGSID without conversation traversal or Page permissions. Before querying
the sender, the backend verifies that the token's `/me?fields=user_id` identifies
the receiving account from the webhook. It then requires the profile response's
`id` to match the sender before conditionally filling a NULL username.

## Read-only staging observations, October 14, 2026

- Receiving Instagram professional account: `17841479724216495`, username
  `professordm_appsuite`. The Facebook User candidate can read this account.
- Expected Facebook Page: `1358275557370847`. Page reads require access absent
  from the current candidate. This does not establish that the Page is unlinked.
- Real follower IGSIDs: `4672837849619460` and `2234200840491090`. The Instagram
  Login candidate returned `reddy_arun7` and `akshayvoora`, respectively, with
  matching sender IDs. Both database usernames were still NULL at validation;
  no database update was made by these read-only probes.
- Existing Vault token: previously identified as a Facebook SYSTEM_USER token.
  Candidate `/professordm/staging/meta-page-token-candidate`: identified by Meta's
  token debugger as a Facebook USER token. Both have `instagram_basic` and
  `instagram_manage_messages`; neither is an Instagram Login token.
- The Instagram Login candidate's `/me` returned app-scoped `id`
  `28789161677380659`, webhook account `user_id` `17841479724216495`, and username
  `professordm_appsuite`. The implementation matches `user_id`, not app-scoped
  `id`, to the webhook recipient.
- Backend tests: 33 passed. Coverage includes new and existing NULL usernames,
  populated username skip, missing/failed credentials, unsafe response mapping,
  conditional updates, time budget, batch processing order, and duplicate MIDs.
- The implemented client also passed a read-only live probe for sender
  `4672837849619460`, returning `reddy_arun7` after its account identity check.

## Candidate validation and implementation gate

The candidate was generated through the same app's Instagram Login setup for
`professordm_appsuite`, with `instagram_business_basic` and
`instagram_business_manage_messages`, and stored separately from Vault at
`/professordm/staging/instagram-user-token-candidate` as an SSM SecureString.

Read the candidate only into backend process memory. Before any Vault update:

1. Verify `graph.instagram.com/v26.0/me?fields=id,user_id,username` identifies
   the expected receiving Instagram account. Meta distinguishes app-scoped
   `id` from the professional account's webhook `user_id`.
2. Query an existing real sender IGSID and require an actual username.
3. Reject a candidate that identifies a different receiving account or cannot
   resolve the sender in the current webhook's scope.

## Runtime credentials and reliability

The staging webhook uses the validated token as a separate SSM SecureString:
`/professordm/staging/instagram-profile-tokens/17841479724216495`.
`SSM_INSTAGRAM_PROFILE_TOKEN_PREFIX` configures the prefix; the receiving
Instagram account ID selects the credential. Other receiving accounts need
their own authorized token under that prefix. Missing credentials leave the
username NULL and do not stop ingestion.

The existing Vault secret, its UUID, the backend Vault RPC, and the outbound
Facebook client stay separate from profile enrichment. No migration is needed.
Use the same secure candidate validation before rotating a profile credential.
Meta documents App Dashboard Instagram Login tokens as valid for 60 days;
refresh or replace the token before expiry. Automatic refresh is not part of
this ticket.

All messages in a webhook are persisted and published before enrichment starts.
Only NULL usernames are considered, and repeated followers in one batch are
queried once. Profile credential loading has bounded AWS timeouts and no retry;
Graph and username-update requests have two-second socket timeouts. Enrichment
is skipped when less than 12 seconds of Lambda execution time remain. Provider
errors are caught without logging error messages, bodies, usernames, or tokens.

## Staging deployment

The reviewed change set `scrum96-instagram-profile-20261014` completed on the
existing `professordm` stack in `UPDATE_COMPLETE`. The deployed Lambda source
matches the tested files. The effective changes are Lambda code and the SSM
profile-token prefix; the processed API definition, IAM role, and both queues
are identical to their previous definitions. No resource was replaced.

GET verification returned HTTP 200 for the correct token and 403 for an invalid
token. An empty Instagram POST returned HTTP 200. These smoke checks did not
create followers, inbound rows, or SQS events.

Before the real-DM test, both known follower usernames remained NULL and the
queue had 44 visible messages with zero in flight. A fresh real DM must prove
the automatic database username update, inbound row, SQS event, and HTTP 200
before Scrum-96 is marked done. No PR has been created or merged.

## Official sources

- [Instagram Login User Profile API](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/messaging-api/user-profile)
- [Instagram Login conversations and message sender fields](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/conversations-api)
- [Facebook Login Instagram User Profile API](https://developers.facebook.com/documentation/business-messaging/instagram-messaging/features/user-profile)
- [Conversation participants reference](https://developers.facebook.com/docs/graph-api/reference/v26.0/conversation)
- [Message sender and recipient reference](https://developers.facebook.com/docs/graph-api/reference/v26.0/message)
- [Generate an Instagram Login token in the App Dashboard](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/get-started)
- [Instagram Login authorization and token lifetime](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-instagram-login/business-login)
