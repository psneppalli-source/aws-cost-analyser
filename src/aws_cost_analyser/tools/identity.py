from __future__ import annotations

from typing import Any, cast

from aws_cost_analyser.aws_client import sts_client
from aws_cost_analyser.security.untrusted import sanitize


def get_caller_identity() -> dict[str, Any]:
    """sts:GetCallerIdentity -- which AWS account/principal this server is
    currently authenticated as. Useful for confirming which account's cost
    data a query will return before running it. No parameters."""
    client = sts_client()
    response = client.get_caller_identity()
    return cast(
        "dict[str, Any]",
        sanitize(
            {
                "account": response.get("Account"),
                "arn": response.get("Arn"),
                "user_id": response.get("UserId"),
            }
        ),
    )
