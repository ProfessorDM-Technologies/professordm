"""End-to-end check for delivered questions on staging (SCRUM-135).

Follows each question delivered since --since through the database and the
Lambda logs and prints PASS or FAIL per step. Read-only: it never writes to
AWS or Supabase. It prints ids, statuses and counts only, never DM or answer
text.

Usage (AWS CLI profile for the ProfessorDM account; the expected account id
comes from the environment so it never sits in this public repo):
    export AWS_PROFILE=<profile> PROFESSORDM_AWS_ACCOUNT=<aws-account-id>
    python3.11 scripts/e2e_check.py --since "2026-11-21 22:30"

Needs only the Python standard library and the `aws` CLI.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

REGION = "us-east-1"
SSM_URL = "/professordm/staging/supabase-url"
SSM_KEY = "/professordm/staging/supabase-service-role-key"
LOG_GROUPS = {
    "webhook": "/aws/lambda/professordm-webhook",
    "worker": "/aws/lambda/professordm-ai-worker",
    "send": "/aws/lambda/professordm-staging-instagram-send",
}
EMBEDDING_DIMS = 1536
SENT = {"sent", "delivered"}


# ---------------------------------------------------------------- checks

def leak_phrases(*texts):
    """Pick up to one 4-word phrase per text to search the logs for.

    Only letters and spaces, so the phrase is safe inside a CloudWatch
    filter pattern. Returns [] for texts too short to make a phrase.
    """
    phrases = []
    for text in texts:
        words = re.findall(r"[A-Za-z]{3,}", text or "")
        if len(words) >= 4:
            middle = max(0, len(words) // 2 - 2)
            phrases.append(" ".join(words[middle:middle + 4]))
    return phrases


def embedding_dims(value):
    """Count the numbers in a pgvector value ("[0.1,0.2]" or a list)."""
    if isinstance(value, list):
        return len(value)
    if isinstance(value, str) and value.strip("[] "):
        return len(value.strip("[] ").split(","))
    return 0


def check_question(q, d):
    """Check one delivered question. Returns a list of (step, ok, detail).

    q: the questions row.
    d: everything loaded for it, with keys
       origin (inbound_messages row or None), others (question_text of the
       follower's earlier questions), draft (approved drafts row or None),
       outbound (answer outbound rows), entries (knowledge_entries rows),
       logs (dict of booleans: draft_done, delivery_pass, publish_pass,
       stored), leaks (number of log lines containing DM or answer text).
    """
    steps = []
    origin = d["origin"]
    steps.append(("1 DM stored", bool(origin), "inbound message found" if origin else "no inbound message"))
    category = (origin or {}).get("category")
    steps.append(("2 safety + triage", category == "expert_question", f"category={category}"))

    text = q.get("question_text") or ""
    repeated = sum(1 for other in d["others"] if other and other.strip() and other.strip() in text)
    steps.append(("3 question has only its own DMs", repeated == 0,
                  "no earlier question repeated" if not repeated else f"{repeated} earlier question(s) repeated"))

    draft = d["draft"]
    ai = (draft or {}).get("ai_text")
    steps.append(("4 AI draft written", bool(ai) and d["logs"]["draft_done"],
                  f"ai_text={'yes' if ai else 'no'} log={'yes' if d['logs']['draft_done'] else 'no'}"))

    final = ((draft or {}).get("final_text") or "").strip()
    edited = bool(final) and final != (ai or "").strip()
    approved = bool((draft or {}).get("approved_at"))
    steps.append(("5 creator edited + approved", edited and approved,
                  f"approved={'yes' if approved else 'no'} edited={'yes' if edited else 'no'}"))

    sent = [row for row in d["outbound"] if row.get("status") in SENT]
    delivered = q.get("status") in ("delivered", "accepted") and bool(sent) and d["logs"]["delivery_pass"]
    steps.append(("6 delivered to Instagram", delivered,
                  f"status={q.get('status')} outbound_sent={len(sent)} log={'yes' if d['logs']['delivery_pass'] else 'no'}"))

    entries = d["entries"]
    entry = entries[0] if len(entries) == 1 else {}
    stored = (len(entries) == 1 and entry.get("source") == "question" and (entry.get("content") or "").strip() == final
              and bool(entry.get("tags")) and embedding_dims(entry.get("embedding")) == EMBEDDING_DIMS
              and d["logs"]["publish_pass"] and d["logs"]["stored"])
    steps.append(("7 Q&A saved", stored,
                  f"rows={len(entries)} published={entry.get('published')} tags={len(entry.get('tags') or [])} "
                  f"dims={embedding_dims(entry.get('embedding'))} final_text={'yes' if entry and (entry.get('content') or '').strip() == final else 'no'} "
                  f"publish_log={'yes' if d['logs']['publish_pass'] else 'no'} stored_log={'yes' if d['logs']['stored'] else 'no'}"))

    steps.append(("8 no DM or answer text in logs", d["leaks"] == 0, f"matches={d['leaks']}"))
    return steps


# ---------------------------------------------------------------- loading

def aws(*args):
    out = subprocess.run(["aws", *args, "--region", REGION, "--output", "json"],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out) if out.strip() else {}


def log_lines(group, pattern, start_ms):
    data = aws("logs", "filter-log-events", "--log-group-name", group, "--start-time", str(start_ms),
               "--filter-pattern", pattern)
    return [event["message"] for event in data.get("events", [])]


class Supabase:
    def __init__(self, url, key):
        # Same as the backend: keep only scheme and host of the stored URL.
        parts = urllib.parse.urlsplit(url)
        self.url, self.key = f"{parts.scheme}://{parts.netloc}", key

    def get(self, table, **params):
        query = urllib.parse.urlencode(params)
        request = urllib.request.Request(f"{self.url}/rest/v1/{table}?{query}",
                                         headers={"apikey": self.key, "Authorization": f"Bearer {self.key}"})
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.loads(response.read())


def load(db, q, start_ms):
    qid = q["id"]
    origin = db.get("inbound_messages", id=f"eq.{q['origin_message_id']}", select="id,status,category,received_at")
    others = db.get("questions", follower_id=f"eq.{q['follower_id']}", id=f"neq.{qid}", select="question_text,delivered_at")
    others = [row["question_text"] for row in others
              if row.get("delivered_at") and row["delivered_at"] < (q.get("delivered_at") or "")]
    drafts = db.get("drafts", question_id=f"eq.{qid}", approved_at="not.is.null",
                    select="id,ai_text,final_text,approved_at", order="approved_at.desc", limit="1")
    draft = drafts[0] if drafts else None
    outbound = db.get("outbound_messages", draft_id=f"eq.{draft['id']}", type="eq.answer", select="status") if draft else []
    entries = db.get("knowledge_entries", question_id=f"eq.{qid}", select="source,content,tags,published,embedding")
    logs = {
        "draft_done": bool(log_lines(LOG_GROUPS["worker"], f'"job=draft id=draft:{qid}" "outcome=done"', start_ms)),
        "delivery_pass": bool(log_lines(LOG_GROUPS["send"], f'"stage=answer_delivery PASS question_id={qid}"', start_ms)),
        "publish_pass": bool(log_lines(LOG_GROUPS["send"], f'"stage=store_qa_publish PASS question_id={qid}"', start_ms)),
        "stored": bool(log_lines(LOG_GROUPS["worker"], f'"job=store_qa id=store_qa:{qid}" "status=stored"', start_ms)),
    }
    leaks = sum(len(log_lines(group, f'"{phrase}"', start_ms))
                for phrase in leak_phrases(q.get("question_text"), (draft or {}).get("final_text"))
                for group in LOG_GROUPS.values())
    return {"origin": origin[0] if origin else None, "others": others, "draft": draft, "outbound": outbound,
            "entries": entries, "logs": logs, "leaks": leaks}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since", required=True, help='UTC time, e.g. "2026-11-21 22:30"')
    args = parser.parse_args()
    since = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)

    expected = os.environ.get("PROFESSORDM_AWS_ACCOUNT")
    if not expected:
        sys.exit("Set PROFESSORDM_AWS_ACCOUNT to the ProfessorDM AWS account id.")
    if aws("sts", "get-caller-identity").get("Account") != expected:
        sys.exit("Wrong AWS account. Set AWS_PROFILE to the ProfessorDM account.")
    url = aws("ssm", "get-parameter", "--name", SSM_URL)["Parameter"]["Value"]
    key = aws("ssm", "get-parameter", "--name", SSM_KEY, "--with-decryption")["Parameter"]["Value"]
    db = Supabase(url, key)

    since_iso = since.strftime("%Y-%m-%dT%H:%M:%SZ")
    questions = db.get("questions", delivered_at=f"gte.{since_iso}", order="delivered_at.asc",
                       select="id,status,question_text,origin_message_id,follower_id,delivered_at")
    if not questions:
        print(f"No questions delivered since {since_iso}.")
        return 1
    start_ms = int((since - timedelta(hours=1)).timestamp() * 1000)
    passed = 0
    for q in questions:
        steps = check_question(q, load(db, q, start_ms))
        ok = all(step_ok for _, step_ok, _ in steps)
        passed += ok
        print(f"\nQuestion {q['id'][:8]}  (delivered {q['delivered_at'][:19]} UTC)")
        for name, step_ok, detail in steps:
            print(f"  {name:<34} {'PASS' if step_ok else 'FAIL'}  {detail}")
    print(f"\nRESULT: {passed} of {len(questions)} questions PASS")
    return 0 if passed == len(questions) else 1


if __name__ == "__main__":
    sys.exit(main())
