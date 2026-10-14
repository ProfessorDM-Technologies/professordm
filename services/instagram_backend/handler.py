"""Entry point for the existing professordm-webhook Lambda."""

from runtime import webhook_handler


def lambda_handler(event, context):
    return webhook_handler(event, context)
