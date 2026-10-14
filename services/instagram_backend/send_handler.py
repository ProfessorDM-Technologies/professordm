"""Entry point for POST /api/send."""

from runtime import send_handler


def lambda_handler(event, context):
    return send_handler(event, context)
