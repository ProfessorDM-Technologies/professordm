"""PostgREST client and the queries the AI worker needs.

Same style as services/instagram_backend/clients.py: urllib, JSON, and urlencode
for query strings, so ISO timestamps with "+" are encoded. Every query lives
here as a small method, and they all go through Db.request, so a test can fake
that one method and keep the real filters (test_worker.FakeDb does).

Depends on:
    The standard library only, like llm.py, so the Lambda needs no packaging.

Never does:
    - Decide anything. worker.py picks the statuses and the order of the writes.
    - Keep PostgREST error messages, which can echo request content. Only the
      HTTP status and the PostgREST code are kept.
    - Log. The worker logs ids and error types.
"""

import json
from urllib.error import HTTPError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


# PostgREST's code for a unique violation, returned with HTTP 409.
UNIQUE_VIOLATION = "23505"

_REPRESENTATION = "return=representation"


class DbError(Exception):
    """A Supabase request failed.

    Attributes:
        status (int | None): The HTTP status, or None for a network error.
        code (str | None): The PostgREST code, for example "23505", or
            "network". Safe to log: it never contains DM text.
    """

    def __init__(self, status=None, code=None):
        super().__init__(f"Database request failed ({status or 'network'}, {code or 'unknown'})")
        self.status = status
        self.code = code


def _one(rows):
    """Return the first row of a PostgREST response, or None."""
    return rows[0] if isinstance(rows, list) and rows else None


def _status_filter(statuses):
    """Build the PostgREST filter for "status is one of these".

    Args:
        statuses (tuple[str | None, ...]): The allowed statuses; None means
            the status is empty.

    Returns:
        dict[str, str]: {"status": "eq.x"} for one plain status, otherwise
        {"or": "(status.is.null,status.eq.x,...)"}.

    Side effects: none.
    """
    if len(statuses) == 1 and statuses[0] is not None:
        return {"status": f"eq.{statuses[0]}"}
    parts = ["status.is.null" if status is None else f"status.eq.{status}" for status in statuses]
    return {"or": f"({','.join(parts)})"}


class Db:
    """The service-role PostgREST client, one method per query."""

    def __init__(self, url, service_key, timeout=8):
        """Store the connection settings.

        Args:
            url (str): The Supabase project URL. Must be https.
            service_key (str): The service-role key.
            timeout (float): Seconds per request.

        Raises:
            ValueError: If the URL is not https.

        Side effects: none.
        """
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("Supabase URL must be HTTPS")
        self.base = f"{parsed.scheme}://{parsed.netloc}"
        self.key = service_key
        self.timeout = timeout

    def request(self, method, path, *, params=None, body=None, prefer=None):
        """Make one PostgREST request.

        Args:
            method (str): The HTTP method.
            path (str): The table, for example "inbound_messages".
            params (dict[str, str] | list[tuple[str, str]] | None): Query
                parameters, encoded here.
            body (Any): The JSON body, if any.
            prefer (str | None): The Prefer header, if any.

        Returns:
            Any: The parsed JSON response, or None for an empty one.

        Raises:
            DbError: (status, PostgREST code) on an HTTP error; (None,
                "network") on a timeout, network error or non-JSON response.

        Side effects: one HTTPS request.
        """
        query = f"?{urlencode(params)}" if params else ""
        headers = {"apikey": self.key, "Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        if prefer:
            headers["Prefer"] = prefer
        encoded = json.dumps(body, separators=(",", ":")).encode("utf-8") if body is not None else None
        request = Request(f"{self.base}/rest/v1/{path}{query}", data=encoded, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = response.read()
                return json.loads(payload) if payload else None
        except HTTPError as error:
            try:
                detail = json.loads(error.read())
                code = detail.get("code") if isinstance(detail, dict) else None
            except (ValueError, AttributeError):
                code = None
            raise DbError(error.code, code) from None
        except (OSError, ValueError):
            # OSError covers URLError, timeouts and dropped connections;
            # ValueError covers a response body that is not JSON.
            raise DbError(None, "network") from None

    def _insert(self, table, row):
        """Insert one row, or a list of rows, and return the first one back."""
        return _one(self.request("POST", table, body=row, prefer=_REPRESENTATION))

    # inbound_messages and ig_followers

    def get_message(self, message_id):
        """Load one inbound message (spec 5.1)."""
        return _one(self.request("GET", "inbound_messages", params={
            "id": f"eq.{message_id}", "select": "id,follower_id,text,status,received_at,triage_attempts",
            "limit": "1"}))

    def get_follower(self, follower_id):
        """Load one follower (spec 5.1)."""
        return _one(self.request("GET", "ig_followers", params={
            "id": f"eq.{follower_id}", "select": "id,creator_id,ig_scoped_id", "limit": "1"}))

    def find_open_original(self, follower_id, message_id, received_at, statuses):
        """Find the follower's newest earlier message in one of these statuses (spec 5.2)."""
        status = (f"eq.{statuses[0]}" if len(statuses) == 1 else f"in.({','.join(statuses)})")
        return _one(self.request("GET", "inbound_messages", params={
            "follower_id": f"eq.{follower_id}", "status": status, "id": f"neq.{message_id}",
            "received_at": f"lt.{received_at}", "select": "id,text,status,received_at,triage_attempts",
            "order": "received_at.desc", "limit": "1"}))

    def claim_message(self, message_id, statuses):
        """Move a message to triaging if its status is one of these. Returns the row, or None."""
        return self.update_message_where(message_id, statuses, {"status": "triaging"})

    def update_message(self, message_id, expected_status, values):
        """Update a message only while it has expected_status. Returns the row, or None."""
        return self.update_message_where(message_id, (expected_status,), values)

    def update_message_where(self, message_id, statuses, values):
        """Update a message only while its status is one of these. Returns the row, or None."""
        return _one(self.request("PATCH", "inbound_messages", params={
            "id": f"eq.{message_id}", **_status_filter(statuses)}, body=values, prefer=_REPRESENTATION))

    def recent_messages(self, follower_id, message_id, since, until):
        """Load the follower's other messages in [since, until), oldest first (spec 14).

        A list of pairs, because received_at is filtered twice. Plain filters
        avoid and=(...), whose values PostgREST parses as a logic tree.
        """
        return self.request("GET", "inbound_messages", params=[
            ("follower_id", f"eq.{follower_id}"), ("id", f"neq.{message_id}"),
            ("received_at", f"gte.{since}"), ("received_at", f"lt.{until}"),
            ("select", "text,status"), ("order", "received_at.asc")]) or []

    def get_message_text(self, message_id):
        """Load one message's text (spec 6 step 2)."""
        row = _one(self.request("GET", "inbound_messages", params={"id": f"eq.{message_id}", "select": "text"}))
        return row.get("text") if row else None

    # clarification_rounds

    def get_rounds(self, message_id):
        """Load a message's clarification rounds, lowest round first."""
        return self.request("GET", "clarification_rounds", params={
            "message_id": f"eq.{message_id}", "select": "id,round,prompt,reply", "order": "round.asc"}) or []

    def find_round(self, message_id, round_):
        """Load one clarification round, or None."""
        return _one(self.request("GET", "clarification_rounds", params={
            "message_id": f"eq.{message_id}", "round": f"eq.{round_}", "select": "id"}))

    def insert_round(self, row):
        """Insert one clarification round."""
        return self._insert("clarification_rounds", row)

    def save_reply(self, round_id, text):
        """Save a follower's reply, only while the round has none (spec 5.5 step 6)."""
        self.request("PATCH", "clarification_rounds", params={"id": f"eq.{round_id}", "reply": "is.null"},
                     body={"reply": text})

    # safety_flags

    def get_flags(self, target_type, target_id, checkpoint):
        """Load the flags already on a target at one checkpoint."""
        return self.request("GET", "safety_flags", params={
            "target_type": f"eq.{target_type}", "target_id": f"eq.{target_id}", "checkpoint": f"eq.{checkpoint}",
            "select": "layer,category,detail"}) or []

    def insert_flags(self, rows):
        """Insert safety flag rows, all or none."""
        self.request("POST", "safety_flags", body=rows)

    def risk_topics(self, message_id):
        """Load the message's checkpoint-1 risk topics, the non-null details (spec 6 step 2)."""
        rows = self.request("GET", "safety_flags", params={
            "target_type": "eq.message", "target_id": f"eq.{message_id}", "checkpoint": "eq.1",
            "layer": "eq.policy", "category": "eq.risk_topic", "select": "detail"}) or []
        return [row["detail"] for row in rows if row.get("detail") is not None]

    # outbound_messages

    def insert_outbound(self, row):
        """Insert an outbound row, or return the existing one with the same client_request_id.

        Args:
            row (dict): The outbound_messages row.

        Returns:
            dict | None: A row holding at least "id".

        Raises:
            DbError: On any failure other than a unique violation.

        Side effects: one or two requests.
        """
        try:
            return self._insert("outbound_messages", row)
        except DbError as error:
            if error.code != UNIQUE_VIOLATION:
                raise
        return _one(self.request("GET", "outbound_messages", params={
            "client_request_id": f"eq.{row['client_request_id']}", "select": "id"}))

    # questions

    def find_question(self, origin_message_id):
        """Load the question created from a message, or None."""
        return _one(self.request("GET", "questions", params={
            "origin_message_id": f"eq.{origin_message_id}", "select": "id,status", "limit": "1"}))

    def insert_question(self, row):
        """Insert one question and return it."""
        return self._insert("questions", row)

    def mark_paid(self, question_id, paid_at):
        """Move a question from pending_payment to paid. Returns the row, or None."""
        return _one(self.request("PATCH", "questions", params={
            "id": f"eq.{question_id}", "status": "eq.pending_payment"},
            body={"status": "paid", "paid_at": paid_at}, prefer=_REPRESENTATION))

    def claim_question(self, question_id, statuses):
        """Move a question to drafting if its status is one of these. Returns its fields, or None."""
        return _one(self.request("PATCH", "questions", params={
            "id": f"eq.{question_id}", **_status_filter(statuses),
            "select": "id,creator_id,source,origin_message_id,question_text,safety_flagged"},
            body={"status": "drafting"}, prefer=_REPRESENTATION))

    def update_question(self, question_id, expected_status, status):
        """Change a question's status only while it has expected_status."""
        self.request("PATCH", "questions", params={"id": f"eq.{question_id}", "status": f"eq.{expected_status}"},
                     body={"status": status})

    def flag_question(self, question_id):
        """Mark a question safety_flagged."""
        self.request("PATCH", "questions", params={"id": f"eq.{question_id}"}, body={"safety_flagged": True})

    # drafts

    def find_draft(self, question_id):
        """Load the question's existing draft row, or None."""
        return _one(self.request("GET", "drafts", params={
            "question_id": f"eq.{question_id}", "status": "in.(ready,no_draft)", "select": "id", "limit": "1"}))

    def insert_draft(self, row):
        """Insert one draft row and return it."""
        return self._insert("drafts", row)

    def update_draft(self, draft_id, values):
        """Overwrite a draft row with a newer run's result."""
        self.request("PATCH", "drafts", params={"id": f"eq.{draft_id}"}, body=values)
