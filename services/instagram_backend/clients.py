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
    def __init__(self, status, code=None):
        super().__init__(f"Supabase request failed ({status}, {code or 'unknown'})")
        self.status = status
        self.code = code


def _json_request(url, method, headers, body=None, timeout=8):
    encoded = json.dumps(body, separators=(",", ":")).encode("utf-8") if body is not None else None
    request = Request(url, data=encoded, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read()
            return json.loads(payload) if payload else None
    except HTTPError as error:
        try:
            code = json.loads(error.read()).get("code")
        except (ValueError, AttributeError):
            code = None
        raise RestError(error.code, code) from None


class SupabaseRest:
    def __init__(self, url, service_role_key):
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("Supabase URL must be HTTPS")
        self.base = f"{parsed.scheme}://{parsed.netloc}"
        self.key = service_role_key

    def request(self, method, path, *, params=None, body=None, prefer=None):
        query = f"?{urlencode(params)}" if params else ""
        headers = {"apikey": self.key, "Authorization": f"Bearer {self.key}",
                   "Content-Type": "application/json"}
        if prefer:
            headers["Prefer"] = prefer
        return _json_request(f"{self.base}/rest/v1/{path}{query}", method, headers, body)

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
        self.url = f"https://graph.facebook.com/{version}/me/messages"

    def send(self, token, recipient, text):
        try:
            response = _json_request(self.url, "POST",
                                     {"Authorization": f"Bearer {token}",
                                      "Content-Type": "application/json"},
                                     {"recipient": {"id": recipient}, "message": {"text": text}})
        except RestError:
            raise RuntimeError("Meta delivery failed") from None
        return response.get("message_id") if isinstance(response, dict) else None
