from __future__ import annotations

from botocore.exceptions import ClientError, EndpointConnectionError
from pydantic import BaseModel, ValidationError

from aws_cost_analyser.errors import ToolError, to_safe_error


def test_client_error_returns_code_and_message_without_leaking_internals():
    exc = ClientError(
        error_response={
            "Error": {
                "Code": "AccessDeniedException",
                "Message": "User is not authorized to perform ce:GetCostAndUsage",
            }
        },
        operation_name="GetCostAndUsage",
    )
    message = to_safe_error(exc)
    assert "AccessDeniedException" in message
    assert "not authorized" in message


def test_client_error_message_is_redacted():
    exc = ClientError(
        error_response={
            "Error": {
                "Code": "AccessDeniedException",
                "Message": "Denied for key AKIAABCDEFGHIJKLMNOP",
            }
        },
        operation_name="GetCostAndUsage",
    )
    message = to_safe_error(exc)
    assert "AKIAABCDEFGHIJKLMNOP" not in message


def test_boto_core_error_returns_generic_message():
    exc = EndpointConnectionError(endpoint_url="https://ce.us-east-1.amazonaws.com")
    message = to_safe_error(exc)
    assert "AWS" in message
    assert "Traceback" not in message


def test_validation_error_is_safe_and_descriptive():
    class Model(BaseModel):
        value: int

    try:
        Model(value="not-an-int")
    except ValidationError as exc:
        message = to_safe_error(exc)
        assert "Invalid request" in message
        return
    raise AssertionError("expected ValidationError")


def test_unknown_exception_never_leaks_details():
    try:
        raise RuntimeError("/etc/passwd leaked, SECRET_KEY=abc123, /home/user/.aws/credentials")
    except RuntimeError as exc:
        message = to_safe_error(exc)
    assert "/etc/passwd" not in message
    assert "SECRET_KEY" not in message
    assert "credentials" not in message
    assert message == "An internal error occurred while processing the request."


def test_tool_error_message_passes_through_verbatim():
    exc = ToolError("monitor_arn does not exist in this account")
    assert to_safe_error(exc) == "monitor_arn does not exist in this account"
