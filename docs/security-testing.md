# Security / Penetration-Testing Checklist

This is a checklist for a human/external reviewer, plus a map to the
automated regression tests that already cover each item. **Automated
coverage is not a substitute for independent penetration testing** -- see
`docs/security-report.md` for what has and has not actually been run.

## Authentication

- [ ] AWS credential handling relies only on the boto3 provider chain -- confirm no custom credential path exists. Automated: `tests/security/test_no_hardcoded_credentials.py`.
- [ ] MCP transport has no authentication because it has no network exposure (stdio only) -- confirm no network listener was added. Manual: review `server.py`/`Dockerfile` for `EXPOSE`, socket binds.
- [ ] Cross-account `AssumeRole` uses a fixed, validated ARN + optional ExternalId. Automated: `tests/security/test_invalid_arn_rejected.py`.

## Authorization

- [ ] IAM policy is read-only, no wildcard actions, only the 6 documented actions. Automated: `tests/security/test_iam_policy_is_read_only.py`.
- [ ] No tool can create/modify/delete any AWS resource. Automated: `tests/security/test_destructive_aws_actions_unavailable.py`.
- [ ] Cross-account access cannot be redirected by tool input (confused deputy). Automated: `tests/security/test_invalid_arn_rejected.py::test_wildcard_role_can_never_be_assumed`.

## Injection

- [ ] Prompt injection via AWS-returned tag/service/cost-category data. Automated: `tests/security/test_untrusted_resource_metadata_not_treated_as_instruction.py`. Manual: attempt to tag a real AWS resource with adversarial text and confirm the MCP client does not execute it as an instruction (client-side behavior, out of this server's control -- see threat model T5).
- [ ] Command injection -- no subprocess/shell path exists. Automated: `tests/security/test_no_arbitrary_code_execution.py`.
- [ ] Path traversal -- no filesystem tool exists. Automated: `tests/security/test_path_traversal_blocked.py`.
- [ ] SSRF / metadata endpoint (169.254.169.254) access -- no HTTP-fetch tool exists. Automated: `tests/security/test_private_network_blocked.py`.
- [ ] SQL injection -- not applicable, no database in this codebase.
- [ ] Template injection -- not applicable, no template engine in this codebase.

## MCP

- [ ] Tool poisoning / misleading descriptions -- manually review every `@mcp.tool()` docstring against actual behavior. Automated (behavioral guarantee only): `tests/security/test_destructive_aws_actions_unavailable.py`.
- [ ] Tool parameter manipulation (oversized ranges, malformed dimensions/ARNs/regions). Automated: `tests/unit/test_validation.py`, `tests/security/test_invalid_region_rejected.py`.
- [ ] Confused deputy via cross-account role. Automated: see Authorization above.
- [ ] Excessive tool permissions. Automated: `tests/security/test_iam_policy_is_read_only.py`.
- [ ] Sensitive output exposure (account IDs, ARNs) -- confirm this is acceptable for the intended use case (a cost-analysis tool inherently returns account/billing identifiers); confirm no *credential* material is ever returned. Automated: `tests/security/test_sensitive_error_information_not_returned.py`.

## AWS

- [ ] IAM privilege escalation path -- confirm none exists (no `iam:*`, no `sts:AssumeRole` beyond the fixed configured role). Automated: `tests/security/test_iam_policy_is_read_only.py`, `tests/security/test_destructive_aws_actions_unavailable.py`.
- [ ] Credential exposure in logs/errors. Automated: `tests/security/test_aws_credentials_never_logged.py`, `tests/security/test_sensitive_headers_redacted.py`.
- [ ] EC2/ECS metadata endpoint access. Automated: `tests/security/test_private_network_blocked.py`.
- [ ] Cross-account access restricted to the configured role only. Automated: `tests/security/test_invalid_arn_rejected.py`.

## Application

- [ ] Input validation on every tool parameter. Automated: `tests/unit/test_validation.py`.
- [ ] Error handling never leaks internals. Automated: `tests/security/test_sensitive_error_information_not_returned.py`.
- [ ] Logging never leaks secrets. Automated: `tests/security/test_aws_credentials_never_logged.py`.
- [ ] DoS via unbounded pagination / oversized ranges. Automated: `tests/security/test_excessive_pagination_rejected.py`.
- [ ] Dependency vulnerabilities. Automated: `pip-audit` in `scripts/security_gate.py`; see `docs/security-report.md`.

## Container

- [ ] Non-root execution. Manual review: `Dockerfile` (`USER appuser`).
- [ ] No privileged mode required. Manual review: `README.md` run instructions (no `--privileged`).
- [ ] No secrets baked into the image. Manual review: `Dockerfile`, `.dockerignore`.
- [ ] Filesystem access minimal / `--read-only` compatible. Manual: run with `--read-only --cap-drop=ALL` and confirm the server still starts.
- [ ] Network exposure -- confirm no `EXPOSE`d port. Manual review: `Dockerfile`.
- [ ] Base image vulnerability scan. **Not run in this environment** -- see `docs/security-report.md` (Docker daemon unavailable at build time). Recommended before production use: `trivy image <tag>` or `grype <tag>`.

## Recommended scope for an independent penetration test

1. MCP tool-call fuzzing (malformed/boundary values across every field in `validation.py`) against a real AWS test account with the least-privilege IAM policy attached.
2. Attempt to use returned AWS metadata (tags, service names) to influence the behavior of an actual downstream LLM client consuming this server's output (T5 in the threat model -- this is really a test of the client/agent framework, but worth validating end-to-end).
3. Container image vulnerability scan and runtime hardening review (Trivy/Grype + Docker Bench for Security).
4. Dependency supply-chain review beyond `pip-audit` (e.g. manual review of new/uncommon transitive dependencies).
5. Confirm the cross-account `AssumeRole` trust policy example in `iam/assume-role-trust-policy.example.json` cannot be abused if deployed as-is (i.e. the operator replaces the placeholder ExternalId with a real secret).
