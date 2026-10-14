"""AWS Lambda wiring. Secrets stay in SSM and are cached per execution environment."""

from functools import lru_cache
from datetime import datetime, timezone
import logging
import os

import boto3

from clients import MetaGraph, SqsPublisher, SupabaseAuth, SupabaseRepository, SupabaseRest, SupabaseVault
from sender import handle_send
from webhook import handle_webhook


logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
_session = boto3.Session()
_ssm = _session.client("ssm")
_sqs = _session.client("sqs")


def _allow_unverified_staging_webhook(event, context):
    """Time-bound bypass for the one staging REST API route only."""
    if os.environ.get("ALLOW_UNVERIFIED_META_WEBHOOKS") != "true":
        return False
    if getattr(context, "invoked_function_arn", None) != (
            "arn:aws:lambda:us-east-1:939603205947:function:professordm-webhook"):
        return False
    request = event.get("requestContext") or {}
    if (event.get("httpMethod") != "POST" or event.get("path") != "/webhook"
            or request.get("apiId") != "ycmf4156e3" or request.get("stage") != "Prod"):
        return False
    try:
        deadline = datetime.fromisoformat(os.environ["UNVERIFIED_META_WEBHOOK_EXPIRES_AT"].replace("Z", "+00:00"))
        return deadline.tzinfo is not None and datetime.now(timezone.utc) < deadline
    except (KeyError, ValueError):
        return False


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
        verify_token = _parameter("SSM_META_VERIFY_TOKEN")
        if event.get("httpMethod") == "GET":
            result = handle_webhook(event, verify_token=verify_token, app_secret="",
                                    repository=None, publisher=None)
            logger.info("Instagram webhook method=GET status=%s", result["statusCode"])
            return result
        rest = _supabase()
        publisher = SqsPublisher(_sqs, os.environ["QUEUE_URL"])
        result = handle_webhook(event, verify_token=verify_token,
                                app_secret=_parameter("SSM_META_APP_SECRET"),
                                repository=SupabaseRepository(rest), publisher=publisher,
                                allow_unverified=_allow_unverified_staging_webhook(event, context))
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
