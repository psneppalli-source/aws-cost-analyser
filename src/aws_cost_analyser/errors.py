"""Safe, client-facing error mapping.

Never let a raw exception (stack trace, internal file paths, env var
values) reach the MCP client. Known AWS errors are surfaced with their AWS
error code and AWS's own (redacted) message, since that's the information
the caller needs to fix their request. Everything else becomes a single
generic message; full detail is logged server-side only.
"""

from __future__ import annotations

import logging

from botocore.exceptions import BotoCoreError, ClientError
from pydantic import ValidationError

from aws_cost_analyser.security.redaction import redact

logger = logging.getLogger(__name__)


class ToolError(Exception):
    """A safe-to-display error raised deliberately by tool code."""


def to_safe_error(exc: Exception) -> str:
    """Convert any exception into a message safe to return to the MCP client."""
    if isinstance(exc, ToolError):
        return str(exc)

    if isinstance(exc, ValidationError):
        # Pydantic messages describe the offending field/constraint only --
        # safe to return, and useful for the caller to correct their input.
        return f"Invalid request: {redact(str(exc))}"

    if isinstance(exc, ClientError):
        error = exc.response.get("Error", {})
        code = error.get("Code", "AWSError")
        message = error.get("Message", "The AWS API rejected the request.")
        logger.warning("AWS ClientError code=%s", code, exc_info=True)
        return f"AWS error ({code}): {redact(message)}"

    if isinstance(exc, BotoCoreError):
        logger.warning("AWS SDK error", exc_info=True)
        return "The request to AWS could not be completed. Please try again."

    logger.error("Unhandled error in tool execution", exc_info=True)
    return "An internal error occurred while processing the request."
