"""Lambda entry for professordm-ai-worker.

Reads one SQS record at a time, loads the secrets once per container and hands
the job to worker.run_job. A job that needs a retry is reported in
batchItemFailures, so SQS redelivers only that one.

Depends on:
    boto3 from the Lambda runtime, imported inside functions so tests can run
    without it.
    worker for the job logic and db for the Supabase client.
    Environment variables SSM_SUPABASE_URL, SSM_SUPABASE_KEY, SSM_OPENAI_KEY,
    SSM_OPENROUTER_KEY and AI_JOBS_QUEUE_URL.

Never does:
    - Log secrets, DM text or any other job content.
"""

from functools import lru_cache
import json
import logging
import os
from urllib.parse import urlsplit

from db import Db
import worker


# The variable llm.py or knowledge.py reads, and the variable naming its SSM parameter.
SECRETS = (("SUPABASE_URL", "SSM_SUPABASE_URL"),
           ("SUPABASE_SERVICE_ROLE_KEY", "SSM_SUPABASE_KEY"),
           ("OPENAI_API_KEY", "SSM_OPENAI_KEY"),
           ("OPENROUTER_API_KEY", "SSM_OPENROUTER_KEY"))

# Seconds before a retry, per delivery so far: about 1 then 2 minutes instead
# of the queue's 12 minute visibility timeout.
BACKOFF_SECONDS = 60

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


@lru_cache(maxsize=1)
def _sqs():
    """Return the SQS client, created once per container."""
    import boto3
    return boto3.client("sqs")


@lru_cache(maxsize=1)
def _load_secrets():
    """Copy the secrets from SSM into the environment, once per container.

    A failure is not cached, so the next job tries again.

    Returns:
        None

    Raises:
        RuntimeError: If a parameter name is not configured or has no value.
            The message names the variable, never a value.

    Side effects: up to four SSM calls, and sets os.environ.
    """
    import boto3
    ssm = boto3.client("ssm")
    for variable, name_variable in SECRETS:
        name = os.environ.get(name_variable)
        if not name:
            raise RuntimeError(f"Missing {name_variable} parameter name")
        value = ssm.get_parameter(Name=name, WithDecryption=True).get("Parameter", {}).get("Value")
        if not value:
            raise RuntimeError(f"No value for {name_variable}")
        if variable == "SUPABASE_URL":
            # The SSM value ends in /rest/v1/, and knowledge.py appends the
            # whole RPC path, so only the scheme and host are kept here.
            parts = urlsplit(value)
            value = f"{parts.scheme}://{parts.netloc}"
        os.environ[variable] = value


@lru_cache(maxsize=1)
def _db():
    """Return the Supabase client, created once per container, after _load_secrets."""
    return Db(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_ROLE_KEY"])


def _publish(queue_url, job):
    """Send one job to a queue, serialized like SqsPublisher."""
    _sqs().send_message(QueueUrl=queue_url, MessageBody=json.dumps(job, separators=(",", ":")))


def _process(record, context):
    """Run one SQS record.

    Args:
        record (dict): The SQS record.
        context (Any): The Lambda context.

    Returns:
        str: "done" or "retry". An invalid job can never succeed, so it is
        "done"; a failure to start can, so it is "retry".

    Side effects: everything worker.run_job does.
    """
    job = worker.parse_job(record.get("body"))
    if job is None:
        return "done"
    try:
        _load_secrets()
        db = _db()
        receive_count = int(record["attributes"]["ApproximateReceiveCount"])
    except Exception as error:
        logger.error("AI worker config_error id=%s error_type=%s", job.get("id"), type(error).__name__)
        return "retry"
    return worker.run_job(job, receive_count=receive_count, db=db, publish=_publish,
                          time_left=lambda: context.get_remaining_time_in_millis() / 1000)


def _backoff(record):
    """Shorten the wait before a retry. Never raises: the retry still happens at the normal timeout."""
    try:
        receive_count = int(record["attributes"]["ApproximateReceiveCount"])
        _sqs().change_message_visibility(QueueUrl=os.environ["AI_JOBS_QUEUE_URL"],
                                         ReceiptHandle=record["receiptHandle"],
                                         VisibilityTimeout=BACKOFF_SECONDS * receive_count)
    except Exception as error:
        logger.warning("AI worker stage=backoff FAIL error_type=%s", type(error).__name__)


def lambda_handler(event, context):
    """Run every record and report the ones to retry.

    Args:
        event (dict): The SQS event. BatchSize is 1, but this loops anyway.
        context (Any): The Lambda context.

    Returns:
        dict: {"batchItemFailures": [{"itemIdentifier": messageId}, ...]}.

    Side effects: see _process and _backoff.
    """
    failures = []
    for record in event.get("Records", []):
        outcome = _process(record, context)
        if outcome == "retry":
            _backoff(record)
            failures.append({"itemIdentifier": record["messageId"]})
    return {"batchItemFailures": failures}
