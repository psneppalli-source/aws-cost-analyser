"""Section 11 & 31 (test_destructive_aws_actions_unavailable): no tool may
create, modify, or delete anything in AWS -- IAM users/roles, security
controls, billing controls, or any other resource. Verified two ways:
(1) the live MCP tool registry is exactly the fixed read-only allowlist,
and (2) no boto3 client call anywhere in tools/ uses a mutating verb."""

from __future__ import annotations

import re

from tests.security._paths import SRC_ROOT

READ_ONLY_VERB_PREFIXES = ("get_", "list_", "describe_")

_CLIENT_CALL_RE = re.compile(r"\bclient\.([a-z_]+)\(")


def test_registered_tools_match_the_fixed_read_only_allowlist():
    from aws_cost_analyser.server import EXPECTED_TOOL_NAMES, mcp

    registered = {t.name for t in mcp._tool_manager.list_tools()}
    assert registered == EXPECTED_TOOL_NAMES


def test_no_mutating_boto3_calls_in_tool_implementations():
    offenders = []
    for path in (SRC_ROOT / "tools").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        for match in _CLIENT_CALL_RE.finditer(text):
            method = match.group(1)
            if not method.startswith(READ_ONLY_VERB_PREFIXES):
                offenders.append((str(path), method))
    assert offenders == [], f"Non-read-only AWS SDK call found: {offenders}"


def test_no_iam_or_billing_control_apis_referenced_anywhere():
    """Section 11: creating IAM users/access keys, attaching policies,
    disabling CloudTrail, or touching billing controls must not be
    reachable from this codebase at all."""
    forbidden_substrings = [
        "create_user",
        "create_access_key",
        "attach_role_policy",
        "attach_user_policy",
        "put_role_policy",
        "assume_role_with_saml",  # not used; only plain AssumeRole with a fixed ARN is
        "stop_logging",  # CloudTrail
        "delete_trail",
        "put_account_public_access_block",
    ]
    offenders = []
    for path in SRC_ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in forbidden_substrings:
            if token in text:
                offenders.append((str(path), token))
    assert offenders == [], f"Forbidden privileged/destructive API reference found: {offenders}"
