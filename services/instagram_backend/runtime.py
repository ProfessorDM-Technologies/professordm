"""AWS Lambda wiring. Secrets stay in SSM and are cached per execution environment."""

from functools import lru_cache
import logging
import os

import boto3
from botocore.config import Config

from clients import MetaGraph, SqsPublisher, SsmProfileTokens, SupabaseAuth, SupabaseRepository, SupabaseRest, SupabaseVault
from sender import handle_send
from webhook import handle_webhook


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
_session = boto3.Session()
_ssm = _session.client("ssm")
_sqs = _session.client("sqs")
_profile_ssm = _session.client("ssm", config=Config(
    connect_timeout=1, read_timeout=1,
    retries={"total_max_attempts": 1, "mode": "standard"}))


@lru_cache(maxsize=4)
def _parameter(variable, decrypt=True):
    name = os.environ.get(variable)
    if not name:
        raise RuntimeError(f"Missing {variable} parameter name")
    value = _ssm.get_parameter(Name=name, WithDecryption=decrypt).get("Parameter", {}).get("Value")
    if not value:
        raise RuntimeError(f"No value for {variable}")
    return value


def _supabase():
    return SupabaseRest(_parameter("SSM_SUPABASE_URL", decrypt=False),
                        _parameter("SSM_SUPABASE_KEY"))


def webhook_handler(event, context):
    try:
        if event.get("httpMethod") == "GET":
            result = handle_webhook(event, verify_token=_parameter("SSM_META_VERIFY_TOKEN"),
                                    repository=None, publisher=None, profile_tokens=None, graph=None)
            logger.info("Instagram webhook method=GET status=%s", result["statusCode"])
            return result
        rest = _supabase()
        publisher = SqsPublisher(_sqs, os.environ["QUEUE_URL"])
        result = handle_webhook(event, verify_token="",
                                repository=SupabaseRepository(rest), publisher=publisher,
                                profile_tokens=SsmProfileTokens(
                                    _profile_ssm, os.environ.get("SSM_INSTAGRAM_PROFILE_TOKEN_PREFIX")),
                                graph=MetaGraph(os.environ.get("META_GRAPH_API_VERSION")),
                                remaining_time_ms=context.get_remaining_time_in_millis)
        logger.info("Instagram webhook method=%s status=%s", event.get("httpMethod"),
                    result["statusCode"])
        return result
    except Exception as error:
        logger.error("Instagram webhook failed error_type=%s", type(error).__name__)
        return {"statusCode": 500, "body": "Webhook processing failed"}


def send_handler(event, context):
    try:
        rest = _supabase()
        return handle_send(event, auth=SupabaseAuth(rest),
                           repository=SupabaseRepository(rest),
                           vault=SupabaseVault(rest),
                           graph=MetaGraph(os.environ.get("META_GRAPH_API_VERSION")))
    except Exception as error:
        logger.error("Instagram send failed", extra={"error_type": type(error).__name__})
        return {"statusCode": 500, "headers": {"Content-Type": "application/json"},
                "body": '{"error":"Send processing failed"}'}
