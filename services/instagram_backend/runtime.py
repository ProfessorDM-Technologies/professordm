"""AWS Lambda wiring. Secrets stay in SSM and are cached per execution environment."""

from functools import lru_cache
import logging
import os

import boto3

from clients import MetaGraph, SqsPublisher, SupabaseAuth, SupabaseRepository, SupabaseRest, SupabaseVault
from sender import handle_send
from webhook import handle_webhook


logger = logging.getLogger(__name__)
_session = boto3.Session()
_ssm = _session.client("ssm")
_sqs = _session.client("sqs")


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
            return handle_webhook(event, verify_token=verify_token, app_secret="",
                                  repository=None, publisher=None)
        rest = _supabase()
        publisher = SqsPublisher(_sqs, os.environ["QUEUE_URL"])
        return handle_webhook(event, verify_token=verify_token,
                              app_secret=_parameter("SSM_META_APP_SECRET"),
                              repository=SupabaseRepository(rest), publisher=publisher)
    except Exception as error:
        logger.error("Instagram webhook failed", extra={"error_type": type(error).__name__})
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
