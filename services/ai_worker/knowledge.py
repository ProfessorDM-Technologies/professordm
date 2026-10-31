"""Knowledge base search: one query embedding plus the match_knowledge RPC.

search() embeds the question text, asks Supabase's match_knowledge function
(migration 010, spec section 5) for one creator's best chunks, then caps how
many chunks a single guide may contribute, so one long guide cannot fill every
passage slot of a draft.

Contents:
    SUPABASE_TIMEOUT, RPC_PATH, HPA_TAG, EXCLUDE_TAGS_ENV
        Request settings and the tag and environment names search relies on.
    search(query_text, creator_id, *, k=8, candidates=20, per_doc=3,
           sources=None, published_only=False, exclude_tags=None,
           embed=None, rpc=None)
        The hybrid search (meaning plus keywords), read-only.

Depends on:
    The standard library only (json, logging, os, time, urllib), like llm.py,
    so the Lambda needs no packaging.
    llm for embed() (the query vector) and LLMError (every Supabase failure
    is raised as one, so the worker retries it like a model outage).
    Environment variables SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY and
    optionally KB_EXCLUDE_TAGS, read at call time, never at import.

Never does:
    - Write to the database. match_knowledge is a stable SQL function and the
      POST only calls it.
    - Retry. Embedding is fail-fast and a failed RPC raises at once; the
      worker retries the whole job from the queue.
    - Log query text, passage text, titles or keys. Logs carry result counts,
      the best similarity, HTTP status, error codes and latency only.
"""

import json
import logging
import os
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import llm


# Seconds before the RPC gives up. match_knowledge is a full scan over a few
# thousand rows (no vector index, spec section 4), which takes well under a
# second; 10 s covers a cold connection and still leaves the 120 s draft
# Lambda time for the model calls.
SUPABASE_TIMEOUT = 10

# The PostgREST path of the search function, appended to SUPABASE_URL.
RPC_PATH = "/rest/v1/rpc/match_knowledge"

# Tag prefix that carries a chunk's guide id (build_rows.py writes
# "hpa:HPA-FUND-0001"). Tags are namespaced, so this never clashes with the
# display tags on published Q&A.
HPA_TAG = "hpa:"

# Comma-separated tags to leave out when the caller passes exclude_tags=None:
# empty on staging, "review:pending" in production so guides the expert has not
# approved yet are never drafted from (spec decision D4).
EXCLUDE_TAGS_ENV = "KB_EXCLUDE_TAGS"

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _env(variable):
    """Read one required setting from the environment at call time.

    Args:
        variable (str): The environment variable name.

    Returns:
        str: The value.

    Raises:
        RuntimeError: If the variable is missing or empty. The message names
            the variable, never a value.

    Side effects: none.
    """
    value = os.environ.get(variable)
    if not value:
        raise RuntimeError(f"Missing {variable}")
    return value


def _env_exclude_tags():
    """Read the default exclude list from KB_EXCLUDE_TAGS.

    Returns:
        list[str] | None: The comma-separated tags, each trimmed, empties
        dropped. None when the variable is unset or holds no tags, which
        means "exclude nothing" to match_knowledge.

    Side effects: none.
    """
    tags = [tag.strip() for tag in os.environ.get(EXCLUDE_TAGS_ENV, "").split(",") if tag.strip()]
    return tags or None


def _post(url, headers, body, timeout):
    """POST a JSON body to Supabase and return the parsed JSON response.

    Same pattern as services/instagram_backend/clients._json_request, with
    every failure turned into llm.LLMError so draft() handles one exception
    type for every outage.

    Args:
        url (str): The endpoint.
        headers (dict[str, str]): Request headers, including the service key.
        body (dict): The JSON body.
        timeout (float): Seconds before giving up.

    Returns:
        Any: The parsed JSON response (a list of rows for the RPC).

    Raises:
        llm.LLMError: ("supabase", status, code) on an HTTP error, where code
            is the PostgREST error code (for example "PGRST202") and never its
            message, which can echo request content; ("supabase", None,
            exception name) on a timeout, network error or non-JSON body.

    Side effects: one HTTPS request.
    """
    request = Request(url, data=json.dumps(body, separators=(",", ":")).encode("utf-8"),
                      headers=headers, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except HTTPError as error:
        # PostgREST errors look like {"code", "details", "hint", "message"}.
        # Only the code is kept.
        try:
            detail = json.loads(error.read())
            code = detail.get("code") if isinstance(detail, dict) else None
        except (ValueError, AttributeError):
            code = None
        raise llm.LLMError("supabase", error.code, code) from None
    except (OSError, ValueError) as error:
        # OSError covers URLError, timeouts and dropped connections; ValueError
        # covers a response body that is not JSON.
        raise llm.LLMError("supabase", None, type(error).__name__) from None


def _supabase_rpc():
    """Build the default rpc callable from the environment.

    The settings are read here, before search() embeds anything, so a missing
    variable fails without spending an embedding call.

    Returns:
        callable[[dict], Any]: Takes the RPC body and returns the parsed
        response from POST {SUPABASE_URL}/rest/v1/rpc/match_knowledge.

    Raises:
        RuntimeError: If SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY is missing.

    Side effects: none (the request happens when the callable is called).
    """
    url = _env("SUPABASE_URL").rstrip("/") + RPC_PATH
    key = _env("SUPABASE_SERVICE_ROLE_KEY")
    headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    return lambda body: _post(url, headers, body, SUPABASE_TIMEOUT)


def _hpa_id(tags):
    """Read the guide id from a row's tags.

    Args:
        tags (list[str] | None): The row's tags.

    Returns:
        str | None: The value of the first "hpa:" tag, for example
        "HPA-FUND-0001", or None (demo Q&A rows carry none).

    Side effects: none.
    """
    return next((tag[len(HPA_TAG):] for tag in tags or [] if tag.startswith(HPA_TAG)), None)


def _cap(rows, per_doc, k):
    """Keep at most per_doc rows per guide, in order, then the first k.

    Args:
        rows (list[dict]): RPC rows, best first.
        per_doc (int): Most rows kept per doc_id.
        k (int): Most rows returned.

    Returns:
        list[dict]: The kept rows, still best first. A row with a null doc_id
        (a Q&A entry) is its own group, so it is never capped by another.

    Side effects: none.
    """
    kept, per_group = [], {}
    for row in rows:
        group = row.get("doc_id") or ("entry", row.get("id"))
        if per_group.get(group, 0) >= per_doc:
            continue
        per_group[group] = per_group.get(group, 0) + 1
        kept.append(row)
        if len(kept) == k:
            break
    return kept


def search(query_text, creator_id, *, k=8, candidates=20, per_doc=3, sources=None, published_only=False,
           exclude_tags=None, embed=None, rpc=None):
    """Find the best knowledge chunks for a question (spec 6.3).

    Steps: embed query_text (one input, fail-fast); call match_knowledge for
    `candidates` rows, ranked by Reciprocal Rank Fusion of cosine similarity
    and full-text rank; keep at most per_doc rows per guide; return the top k.

    Args:
        query_text (str): The search text (draft() joins the question and the
            clarification replies). Sent to OpenAI and Supabase, never logged.
        creator_id (str): Only this creator's entries are searched.
        k (int): Most results returned.
        candidates (int): Rows the RPC returns before the per-doc cap
            (match_count).
        per_doc (int): Most results from one guide (doc_id).
        sources (list[str] | None): Keep only these knowledge_entries.source
            values, for example ["doc"]; None keeps all.
        published_only (bool): Only published entries (the consumer app).
        exclude_tags (list[str] | None): Drop entries carrying any of these
            tags. None reads KB_EXCLUDE_TAGS. An explicit list always wins,
            and [] means exclude nothing even when the variable is set.
        embed (callable | None): Same contract as llm.embed; None means
            llm.embed, looked up at call time so tests can patch it. Called
            once as embed([query_text], retry=False).
        rpc (callable[[dict], Any] | None): Takes the RPC body and returns its
            rows; None means POST to Supabase with the service key.

    Returns:
        list[dict]: At most k results, best first: {"entry_id": str,
        "doc_id": str | None, "hpa_id": str | None, "source": str,
        "title": str, "content": str, "similarity": float, "score": float}.
        similarity is the cosine similarity (what the draft gate uses);
        score is the RRF value, for ordering only. Empty when nothing matches.

    Raises:
        llm.LLMError: If the embedding fails, or Supabase fails or returns
            something other than a list of rows (code "bad_response").
        RuntimeError: If OPENAI_API_KEY, SUPABASE_URL or
            SUPABASE_SERVICE_ROLE_KEY is missing (checked before any request
            when rpc is the default).

    Side effects: one embeddings request, one RPC request and one log line
    (counts, best similarity and latency, never text). On a Supabase failure
    a warning line with the status and code instead.
    """
    started = time.monotonic()
    rpc = rpc or _supabase_rpc()
    embed = embed or llm.embed
    # Only None falls back to the environment: [] is a deliberate "exclude
    # nothing" (eval_retrieval.py --live passes it), so no falsy check here.
    if exclude_tags is None:
        exclude_tags = _env_exclude_tags()
    vectors, _ = embed([query_text], retry=False)
    body = {"query_embedding": vectors[0], "query_text": query_text, "p_creator_id": creator_id,
            "match_count": candidates, "p_sources": None if sources is None else list(sources),
            "p_published_only": published_only,
            "p_exclude_tags": None if exclude_tags is None else list(exclude_tags)}
    try:
        rows = rpc(body)
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise llm.LLMError("supabase", None, "bad_response")
    except llm.LLMError as error:
        logger.warning("Knowledge stage=search FAIL status=%s error=%s latency_ms=%d",
                       error.status or "network", error.code or "unknown", int((time.monotonic() - started) * 1000))
        raise
    results = [{"entry_id": row.get("id"), "doc_id": row.get("doc_id"), "hpa_id": _hpa_id(row.get("tags")),
                "source": row.get("source"), "title": row.get("title"), "content": row.get("content"),
                "similarity": row.get("similarity"), "score": row.get("score")}
               for row in _cap(rows, per_doc, k)]
    best = max((result["similarity"] for result in results), default=None)
    logger.info("Knowledge stage=search PASS candidates=%d results=%d best_similarity=%s latency_ms=%d",
                len(rows), len(results), "none" if best is None else f"{best:.3f}",
                int((time.monotonic() - started) * 1000))
    return results
