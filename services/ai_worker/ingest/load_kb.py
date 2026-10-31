# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Load rows.jsonl into Supabase: upsert guides and chunks, drop stale chunks.

Ingest step 5 of 5 (spec sections 3.5 and 14.2). Run by Karthik, or anyone
given the service-role key for one run, against staging. Reads the
rows.jsonl that build_rows.py wrote and talks to PostgREST.

Contents:
    BATCH            rows per upsert request
    urllib_transport the real HTTP transport (tests pass a fake)
    plan             rows.jsonl records -> docs, entries per doc, demo vectors
    load             the real run (4 steps, in order)
    dry_run          the same plan, read-only
    main             the CLI

A real run, in this order:
    1. upsert knowledge_docs      POST ?on_conflict=id, merge-duplicates
    2. upsert knowledge_entries   the same, in batches of BATCH
    3. delete stale chunks        per guide, entries of that doc whose id was
                                  not just loaded (a guide that got shorter
                                  leaves nothing behind)
    4. demo embeddings            PATCH each demo entry only where embedding
                                  is still null; no other column is touched
Every step is idempotent, so a re-run (after a failure, or a new build) is
safe.

Usage (from the repo root):
    SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... \\
    uv run --python 3.11 services/ai_worker/ingest/load_kb.py [--rows FILE] [--dry-run]

Depends on: the standard library only, and the environment variables
SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY (never a file or an argument).

Never does: print keys, the creator id, titles, content or vectors (output
is counts, guide ids, row ids and HTTP statuses only); delete a
knowledge_docs row (extra docs are only reported); write anything with
--dry-run.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


HERE = Path(__file__).resolve().parent
# Default input, under the git-ignored private/.
ROWS_FILE = HERE / "private" / "rows.jsonl"

# Rows per upsert request (spec 3.5). 50 chunks with their 1536-number
# vectors are about 1.5 MB of JSON: well inside PostgREST's request limit,
# and a failed request is cheap to repeat.
BATCH = 50

# Seconds per request. Upserts with vectors are the slowest call, typically
# under 5 s.
TIMEOUT = 60

# What PostgREST should send back. Upserts and deletes need no body; the
# demo PATCH returns the updated ids, so an empty list means the row already
# had an embedding.
UPSERT_PREFER = "resolution=merge-duplicates,return=minimal"
MINIMAL_PREFER = "return=minimal"
RETURN_PREFER = "return=representation"


class LoadError(Exception):
    """A PostgREST request failed.

    Attributes:
        step (str): Which step failed, for example "upsert knowledge_entries".
        status (int | None): The HTTP status, or None for a network error.
    """

    def __init__(self, step, status):
        """Store the step and status in a short message with no response body.

        Args:
            step (str): The failing step.
            status (int | None): The HTTP status, if any.

        Side effects: none.
        """
        super().__init__(f"{step} failed (HTTP {status if status is not None else 'network error'})")
        self.step = step
        self.status = status


def urllib_transport(method, url, headers, body=None):
    """Send one HTTP request with urllib and parse any JSON reply.

    The only function here that touches the network; tests pass a fake with
    the same signature.

    Args:
        method (str): "GET", "POST", "PATCH" or "DELETE".
        url (str): The full URL.
        headers (dict[str, str]): Request headers.
        body (Any): A JSON-serializable body, or None for no body.

    Returns:
        tuple[int | None, Any]: (status, data). data is the parsed JSON, or
        None for an empty reply. An HTTP error gives (its status, None); a
        network error or a reply that is not JSON gives (None, None). The
        error body is dropped, since it can echo request content.

    Side effects: one HTTPS request.
    """
    data = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=TIMEOUT) as response:
            raw = response.read()
            return response.status, json.loads(raw) if raw else None
    except HTTPError as error:
        return error.code, None
    except (OSError, ValueError):
        return None, None


def _env(variable):
    """Read a required environment variable.

    Args:
        variable (str): Its name.

    Returns:
        str: The value.

    Raises:
        SystemExit: If it is missing or empty. The message names the
            variable, never a value.

    Side effects: none.
    """
    value = os.environ.get(variable)
    if not value:
        sys.exit(f"Missing {variable} in the environment")
    return value


def plan(records):
    """Group rows.jsonl records for loading.

    Args:
        records (list[dict]): The rows.jsonl records.

    Returns:
        dict: {"creator_id": str, "docs": [doc row, ...],
        "entries": {doc_id: [entry row, ...]} (one key per doc, in docs
        order), "demo": [{"id", "embedding"}, ...]}. Rows have "table" and
        "op" removed, so they are the request bodies as sent.

    Raises:
        ValueError: For an unknown table or op, rows of more than one
            creator, or an entry whose doc_id has no knowledge_docs row
            (counts and ids in the message only).

    Side effects: none.
    """
    docs, entries, demo = [], [], []
    for record in records:
        kind = (record.get("table"), record.get("op"))
        row = {k: v for k, v in record.items() if k not in ("table", "op")}
        if kind == ("knowledge_docs", "upsert"):
            docs.append(row)
        elif kind == ("knowledge_entries", "upsert"):
            entries.append(row)
        elif kind == ("knowledge_entries", "set_embedding"):
            demo.append({"id": row["id"], "embedding": row["embedding"]})
        else:
            raise ValueError(f"unknown record table={kind[0]} op={kind[1]}")
    creators = {row["creator_id"] for row in docs + entries}
    if len(creators) > 1:
        raise ValueError(f"rows belong to {len(creators)} creators, expected 1")
    by_doc = {doc["id"]: [] for doc in docs}
    for entry in entries:
        if entry["doc_id"] not in by_doc:
            raise ValueError(f"entry {entry['id']} has no knowledge_docs row for doc_id {entry['doc_id']}")
        by_doc[entry["doc_id"]].append(entry)
    return {"creator_id": next(iter(creators), None), "docs": docs, "entries": by_doc, "demo": demo}


def _guide(doc):
    """Return a guide's hpa id for printing.

    Args:
        doc (dict): A knowledge_docs row.

    Returns:
        str: The file name in storage_path without ".docx" (the hpa id),
        never the creator id in front of it.

    Side effects: none.
    """
    return Path(doc.get("storage_path") or doc["id"]).stem


def _in_list(ids):
    """Format ids for a PostgREST in.() or not.in.() filter.

    Args:
        ids (list[str]): UUIDs.

    Returns:
        str: "(id1,id2,...)". UUIDs need no quoting.

    Side effects: none.
    """
    return "(" + ",".join(ids) + ")"


def _stale_filter(doc_id, entries):
    """Build the filter that matches one guide's stale chunks.

    Args:
        doc_id (str): The guide's knowledge_docs id.
        entries (list[dict]): The entry rows just loaded for it.

    Returns:
        str: "doc_id=eq.<doc_id>&id=not.in.(<ids>)", or only the doc_id part
        when the guide has no entries (then all its old chunks are stale).

    Side effects: none.
    """
    query = f"doc_id=eq.{doc_id}"
    if entries:
        query += "&id=not.in." + _in_list([entry["id"] for entry in entries])
    return query


class Client:
    """PostgREST calls with the service-role headers and step-named errors."""

    def __init__(self, base_url, key, transport):
        """Remember the REST base URL, the key and the transport.

        Args:
            base_url (str): SUPABASE_URL (the "/rest/v1" path is added here).
            key (str): SUPABASE_SERVICE_ROLE_KEY.
            transport (callable): urllib_transport or a fake.

        Side effects: none.
        """
        self.rest = base_url.rstrip("/") + "/rest/v1/"
        self.key = key
        self.transport = transport

    def call(self, step, method, path, body=None, prefer=None):
        """Send one request and return its parsed reply.

        Args:
            step (str): The step name used in errors.
            method (str): The HTTP method.
            path (str): The table and query, for example
                "knowledge_docs?on_conflict=id".
            body (Any): The JSON body, or None.
            prefer (str | None): The Prefer header, if any.

        Returns:
            Any: The parsed JSON reply, or None for an empty one.

        Raises:
            LoadError: On a network error or any status outside 200 to 299.

        Side effects: one request through the transport.
        """
        headers = {"apikey": self.key, "Authorization": f"Bearer {self.key}",
                   "Content-Type": "application/json"}
        if prefer:
            headers["Prefer"] = prefer
        status, data = self.transport(method, self.rest + path, headers, body)
        if status is None or not 200 <= status < 300:
            raise LoadError(step, status)
        return data


def load(client, loaded):
    """Run the real load: upserts, stale deletes, then demo embeddings.

    Args:
        client (Client): The PostgREST client.
        loaded (dict): From plan().

    Returns:
        dict: Counts {"docs", "entries", "upsert_requests", "stale_deletes",
        "demo_updated", "demo_already_set"}.

    Raises:
        LoadError: On the first failed request; later steps do not run.

    Side effects: writes to knowledge_docs and knowledge_entries.
    """
    counts = {"docs": len(loaded["docs"]), "entries": 0, "upsert_requests": 0,
              "stale_deletes": 0, "demo_updated": 0, "demo_already_set": 0}
    entries = [entry for rows in loaded["entries"].values() for entry in rows]
    for table, rows in (("knowledge_docs", loaded["docs"]), ("knowledge_entries", entries)):
        for start in range(0, len(rows), BATCH):
            client.call(f"upsert {table}", "POST", f"{table}?on_conflict=id",
                        rows[start:start + BATCH], UPSERT_PREFER)
            counts["upsert_requests"] += 1
    counts["entries"] = len(entries)
    for doc_id, rows in loaded["entries"].items():
        client.call("delete stale knowledge_entries", "DELETE",
                    f"knowledge_entries?{_stale_filter(doc_id, rows)}", prefer=MINIMAL_PREFER)
        counts["stale_deletes"] += 1
    for entry in loaded["demo"]:
        updated = client.call("set demo embeddings", "PATCH",
                              f"knowledge_entries?id=eq.{entry['id']}&embedding=is.null&select=id",
                              {"embedding": entry["embedding"]}, RETURN_PREFER)
        counts["demo_updated" if updated else "demo_already_set"] += 1
    return counts


def dry_run(client, loaded):
    """Report what a real run would change, using GET requests only.

    Args:
        client (Client): The PostgREST client.
        loaded (dict): From plan().

    Returns:
        dict: {"guides": [(hpa_id, entries_to_upsert, [stale ids]), ...],
        "demo_would_update": int, "demo_already_set": int,
        "extra_doc_ids": [ids of this creator's knowledge_docs rows that are
        not in the rows file; reported only, never deleted]}.

    Raises:
        LoadError: On the first failed request.

    Side effects: GET requests only; nothing is written.
    """
    guides = []
    for doc in loaded["docs"]:
        rows = loaded["entries"][doc["id"]]
        stale = client.call("check stale knowledge_entries", "GET",
                            f"knowledge_entries?{_stale_filter(doc['id'], rows)}&select=id") or []
        guides.append((_guide(doc), len(rows), [row["id"] for row in stale]))
    demo_ids = [entry["id"] for entry in loaded["demo"]]
    missing = []
    if demo_ids:
        missing = client.call("check demo embeddings", "GET",
                              f"knowledge_entries?id=in.{_in_list(demo_ids)}&embedding=is.null&select=id") or []
    known = {doc["id"] for doc in loaded["docs"]}
    existing = []
    if loaded["creator_id"]:
        existing = client.call("check knowledge_docs", "GET",
                               f"knowledge_docs?creator_id=eq.{loaded['creator_id']}&select=id") or []
    return {"guides": guides, "demo_would_update": len(missing),
            "demo_already_set": len(demo_ids) - len(missing),
            "extra_doc_ids": sorted(row["id"] for row in existing if row["id"] not in known)}


def _print_dry_run(report):
    """Print the dry-run report: counts and ids only.

    Args:
        report (dict): From dry_run().

    Returns:
        None.

    Side effects: prints to stdout.
    """
    print("DRY RUN: nothing written")
    for hpa_id, upserts, stale in report["guides"]:
        print(f"{hpa_id}  upsert={upserts}  stale={len(stale)}" + (f"  stale_ids={','.join(stale)}" if stale else ""))
    print(f"total  guides={len(report['guides'])}  upsert={sum(g[1] for g in report['guides'])}  "
          f"stale={sum(len(g[2]) for g in report['guides'])}  demo_would_update={report['demo_would_update']}  "
          f"demo_already_set={report['demo_already_set']}")
    if report["extra_doc_ids"]:
        print(f"knowledge_docs not in the rows file (not deleted): {','.join(report['extra_doc_ids'])}")


def main(argv=None, transport=urllib_transport):
    """Load rows.jsonl into Supabase, or dry-run it.

    Args (command line):
        --rows FILE   the rows JSONL (default private/rows.jsonl)
        --dry-run     read-only report of what would change

    Args:
        argv (list[str] | None): Arguments for tests; None reads sys.argv.
        transport (callable): The HTTP transport; tests pass a fake.

    Returns:
        None.

    Raises:
        SystemExit: 1 for missing environment variables, an unreadable or
            inconsistent rows file, or any HTTP error (the message names the
            step and status).

    Side effects: HTTP requests to PostgREST (writes unless --dry-run) and
    a printed summary of counts and ids.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", default=str(ROWS_FILE))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    client = Client(_env("SUPABASE_URL"), _env("SUPABASE_SERVICE_ROLE_KEY"), transport)
    try:
        records = [json.loads(line) for line in Path(args.rows).read_text().splitlines() if line.strip()]
        loaded = plan(records)
    except (OSError, ValueError, KeyError) as error:
        sys.exit(f"Cannot read {args.rows}: {type(error).__name__}: {error}")
    try:
        if args.dry_run:
            _print_dry_run(dry_run(client, loaded))
        else:
            counts = load(client, loaded)
            print("  ".join(f"{name}={value}" for name, value in counts.items()))
    except LoadError as error:
        sys.exit(f"load_kb: {error}")


if __name__ == "__main__":
    main()
