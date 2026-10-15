"""Small server-side clients for Supabase, SQS, Vault, and Meta."""

from datetime import datetime, timezone
import json
import re
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from uuid import uuid4

from sender import DuplicateRequest


class RestError(Exception):
    def __init__(self, status, code=None, error_type=None):
        super().__init__(f"Upstream request failed ({status}, {code or 'unknown'})")
        self.status = status
        self.code = code
        self.error_type = error_type


def _json_request(url, method, headers, body=None, timeout=8):
    encoded = json.dumps(body, separators=(",", ":")).encode("utf-8") if body is not None else None
    request = Request(url, data=encoded, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read()
            return json.loads(payload) if payload else None
    except HTTPError as error:
        try:
            detail = json.loads(error.read())
            meta_error = detail.get("error") if isinstance(detail, dict) else None
            code = detail.get("code") if isinstance(detail, dict) else None
            error_type = None
            if isinstance(meta_error, dict):
                code = code or meta_error.get("code")
                error_type = meta_error.get("type")
        except (ValueError, AttributeError):
            code = None
            error_type = None
        raise RestError(error.code, code, error_type) from None


class SupabaseRest:
    def __init__(self, url, service_role_key):
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("Supabase URL must be HTTPS")
        self.base = f"{parsed.scheme}://{parsed.netloc}"
        self.key = service_role_key

    def request(self, method, path, *, params=None, body=None, prefer=None, timeout=8):
        query = f"?{urlencode(params)}" if params else ""
        headers = {"apikey": self.key, "Authorization": f"Bearer {self.key}",
                   "Content-Type": "application/json"}
        if prefer:
            headers["Prefer"] = prefer
        return _json_request(f"{self.base}/rest/v1/{path}{query}", method, headers, body,
                             timeout=timeout)

    def auth_user(self, jwt):
        try:
            return _json_request(f"{self.base}/auth/v1/user", "GET",
                                 {"apikey": self.key, "Authorization": f"Bearer {jwt}"})
        except RestError as error:
            if error.status in (401, 403):
                return None
            raise


def _one(rows):
    return rows[0] if isinstance(rows, list) and rows else None


class SupabaseRepository:
    def __init__(self, rest):
        self.rest = rest

    def find_account_by_ig_user_id(self, recipient_id):
        return _one(self.rest.request("GET", "ig_accounts", params={
            "ig_user_id": f"eq.{recipient_id}", "select": "id,creator_id", "limit": "1"}))

    def upsert_follower(self, creator_id, sender_id, received_at):
        return _one(self.rest.request("POST", "ig_followers", params={"on_conflict": "ig_scoped_id"},
                                      body={"creator_id": creator_id, "ig_scoped_id": sender_id,
                                            "last_inbound_at": received_at},
                                      prefer="resolution=merge-duplicates,return=representation"))

    def update_follower_username_if_missing(self, follower_id, username):
        return bool(_one(self.rest.request("PATCH", "ig_followers", params={
            "id": f"eq.{follower_id}", "username": "is.null"},
            body={"username": username}, prefer="return=representation", timeout=2)))

    def upsert_inbound(self, mid, follower_id, text):
        inserted = _one(self.rest.request("POST", "inbound_messages", params={"on_conflict": "mid"},
                                          body={"mid": mid, "follower_id": follower_id, "text": text},
                                          prefer="resolution=ignore-duplicates,return=representation"))
        if inserted:
            return inserted
        return _one(self.rest.request("GET", "inbound_messages", params={
            "mid": f"eq.{mid}", "select": "id,follower_id", "limit": "1"}))

    def get_inbound(self, message_id):
        return _one(self.rest.request("GET", "inbound_messages", params={
            "id": f"eq.{message_id}", "select": "id,follower_id", "limit": "1"}))

    def get_follower(self, follower_id):
        return _one(self.rest.request("GET", "ig_followers", params={
            "id": f"eq.{follower_id}", "select": "id,ig_scoped_id,creator_id", "limit": "1"}))

    def get_creator_by_profile(self, profile_id):
        return _one(self.rest.request("GET", "creators", params={
            "profile_id": f"eq.{profile_id}", "select": "id", "limit": "1"}))

    def get_ig_account(self, creator_id):
        rows = self.rest.request("GET", "ig_accounts", params={
            "creator_id": f"eq.{creator_id}", "select": "id,creator_id,vault_token_id", "limit": "2"})
        return rows[0] if isinstance(rows, list) and len(rows) == 1 else None

    def create_outbound(self, row):
        try:
            result = self.rest.request("POST", "outbound_messages", body=row, prefer="return=representation")
        except RestError as error:
            if error.status == 409 and error.code == "23505":
                raise DuplicateRequest() from None
            raise
        return _one(result)

    def get_outbound_by_client_request_id(self, request_id):
        return _one(self.rest.request("GET", "outbound_messages", params={
            "client_request_id": f"eq.{request_id}",
            "select": "id,creator_id,status,meta_message_id", "limit": "1"}))

    def update_outbound(self, outbound_id, *, status, meta_message_id=None):
        body = {"status": status}
        if meta_message_id is not None:
            body["meta_message_id"] = meta_message_id
        result = self.rest.request("PATCH", "outbound_messages", params={"id": f"eq.{outbound_id}"},
                                   body=body, prefer="return=representation")
        row = _one(result)
        if not row:
            raise RestError(404, "outbound_not_found")
        return row


class SupabaseAuth:
    def __init__(self, rest):
        self.rest = rest

    def user_id(self, jwt):
        if not jwt:
            return None
        user = self.rest.auth_user(jwt)
        return user.get("id") if isinstance(user, dict) else None


class SupabaseVault:
    def __init__(self, rest):
        self.rest = rest

    def page_token(self, account_id):
        token = self.rest.request("POST", "rpc/meta_page_token_for_account",
                                  body={"p_account_id": account_id})
        return token if isinstance(token, str) and token else None


class SsmProfileTokens:
    """Separate Instagram Login credentials, keyed by receiving account ID."""

    def __init__(self, ssm_client, prefix):
        self.ssm = ssm_client
        self.prefix = prefix.rstrip("/") if prefix else None

    def for_account(self, ig_user_id):
        if not re.fullmatch(r"[0-9]+", ig_user_id or ""):
            raise ValueError("Instagram account ID must be numeric")
        if not self.prefix:
            return None
        response = self.ssm.get_parameter(
            Name=f"{self.prefix}/{ig_user_id}", WithDecryption=True)
        token = response.get("Parameter", {}).get("Value")
        return token if isinstance(token, str) and token else None


class SqsPublisher:
    def __init__(self, sqs_client, queue_url):
        self.sqs = sqs_client
        self.queue_url = queue_url

    def publish(self, message_id, creator_id):
        job = {"v": 1, "type": "triage", "id": f"triage:{message_id}",
               "creatorId": creator_id, "traceId": str(uuid4()),
               "createdAt": datetime.now(timezone.utc).isoformat(),
               "payload": {"messageId": message_id}}
        self.sqs.send_message(QueueUrl=self.queue_url,
                              MessageBody=json.dumps(job, separators=(",", ":")))


class MetaGraph:
    def __init__(self, version):
        if not re.fullmatch(r"v[0-9]+\.[0-9]+", version or ""):
            raise ValueError("META_GRAPH_API_VERSION must be configured")
        self.base = f"https://graph.facebook.com/{version}"
        self.profile_base = f"https://graph.instagram.com/{version}"
        self.url = f"{self.base}/me/messages"

    def user_profile(self, token, ig_user_id, ig_scoped_id):
        if any(not re.fullmatch(r"[0-9]+", value or "")
               for value in (ig_user_id, ig_scoped_id)):
            raise ValueError("Instagram account and scoped IDs must be numeric")
        headers = {"Authorization": f"Bearer {token}"}
        identity = _json_request(f"{self.profile_base}/me?fields=user_id", "GET",
                                 headers, timeout=2)
        # Instagram Login's `id` is app-scoped; `user_id` is the webhook account ID.
        if not isinstance(identity, dict) or identity.get("user_id") != ig_user_id:
            raise ValueError("Instagram token does not match receiving account")
        response = _json_request(
            f"{self.profile_base}/{ig_scoped_id}?{urlencode({'fields': 'id,username,name'})}",
            "GET", headers, timeout=2)
        if not isinstance(response, dict) or response.get("id") != ig_scoped_id:
            raise ValueError("Meta profile does not match webhook sender")
        return {key: response.get(key) for key in ("id", "username", "name")}

    def send(self, token, recipient, text):
        try:
            response = _json_request(self.url, "POST",
                                     {"Authorization": f"Bearer {token}",
                                      "Content-Type": "application/json"},
                                     {"recipient": {"id": recipient}, "message": {"text": text}})
        except RestError:
            raise RuntimeError("Meta delivery failed") from None
        return response.get("message_id") if isinstance(response, dict) else None
