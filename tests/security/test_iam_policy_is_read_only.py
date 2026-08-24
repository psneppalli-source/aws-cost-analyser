"""Section 10 & 31 (test_iam_policy_is_read_only): the shipped IAM policy
must never contain a wildcard action, an admin/power-user managed policy
equivalent, or any action outside the fixed read-only allowlist this
server actually uses."""

from __future__ import annotations

import json

from tests.security._paths import REPO_ROOT

POLICY_PATH = REPO_ROOT / "iam" / "read-only-policy.json"

ALLOWED_ACTIONS = {
    "ce:GetCostAndUsage",
    "ce:GetCostForecast",
    "ce:GetAnomalies",
    "ce:GetDimensionValues",
    "ce:GetTags",
    "sts:GetCallerIdentity",
}

DISALLOWED_ACTION_PREFIXES = ("iam:", "ec2:", "s3:", "billing:", "organizations:")


def _load_policy() -> dict:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def test_policy_file_exists_and_parses():
    policy = _load_policy()
    assert policy["Version"] == "2012-10-17"
    assert policy["Statement"]


def test_no_wildcard_or_admin_actions():
    policy = _load_policy()
    for statement in policy["Statement"]:
        actions = statement["Action"]
        actions = [actions] if isinstance(actions, str) else actions
        for action in actions:
            assert action != "*", "Wildcard action found in IAM policy"
            assert not action.endswith(":*"), f"Service-wide wildcard action found: {action}"


def test_every_action_is_explicitly_allowlisted():
    policy = _load_policy()
    for statement in policy["Statement"]:
        actions = statement["Action"]
        actions = [actions] if isinstance(actions, str) else actions
        for action in actions:
            assert action in ALLOWED_ACTIONS, f"Unexpected IAM action in policy: {action}"


def test_no_mutating_or_out_of_scope_service_actions():
    policy = _load_policy()
    for statement in policy["Statement"]:
        actions = statement["Action"]
        actions = [actions] if isinstance(actions, str) else actions
        for action in actions:
            for prefix in DISALLOWED_ACTION_PREFIXES:
                assert not action.startswith(prefix), f"Disallowed action prefix: {action}"


def test_effect_is_allow_only_no_explicit_deny_bypass_tricks():
    policy = _load_policy()
    for statement in policy["Statement"]:
        assert statement["Effect"] == "Allow"
