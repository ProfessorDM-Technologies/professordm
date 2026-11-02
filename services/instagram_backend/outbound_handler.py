"""Entry point for the professordm-outbound-sender Lambda."""

import json
import logging
import os

from clients import MetaGraph, SsmProfileTokens, SupabaseRepository
from outbound import RETRY, handle_outbound
from runtime import _profile_ssm, _supabase


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def _process(record):
    try:
        job = json.loads(record.get("body"))
    except (TypeError, ValueError):
        job = None  # handle_outbound acknowledges it
    try:
        rest = _supabase(timeout=3)
        return handle_outbound(job, rest=rest, repository=SupabaseRepository(rest),
                               profile_tokens=SsmProfileTokens(
                                   _profile_ssm, os.environ["SSM_INSTAGRAM_PROFILE_TOKEN_PREFIX"]),
                               graph=MetaGraph(os.environ["META_GRAPH_API_VERSION"]))
    except Exception as error:
        # Only setup can raise here, and setup runs before any claim.
        logger.error("Instagram outbound stage=setup FAIL error_type=%s", type(error).__name__)
        return RETRY


def lambda_handler(event, context):
    failures = [{"itemIdentifier": record["messageId"]} for record in event.get("Records", [])
                if _process(record) == RETRY]
    return {"batchItemFailures": failures}
