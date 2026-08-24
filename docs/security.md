# Security Controls

Implemented controls in this codebase, mapped to the standards referenced
in the project brief. This is a mapping of what's *implemented*, not a
certification -- see `docs/security-report.md` for actual scan/test
results and `docs/security-testing.md` for the pentest checklist.

## OWASP Top 10 (2021) / API Security Top 10

| Risk | Control | Where |
|---|---|---|
| A01 Broken Access Control | Fixed, least-privilege IAM policy; no tool can widen its own permissions; cross-account role is fixed at startup, never client-selectable | `iam/read-only-policy.json`, `config.py`, `aws_client.py` |
| A02 Cryptographic Failures | No TLS verification disabled anywhere; boto3's default HTTPS-only endpoints used unmodified | `aws_client.py` (no `verify=False` anywhere in the repo) |
| A03 Injection | No shell/eval/exec/dynamic-import anywhere; all AWS-bound parameters validated against explicit allowlists/regex; AWS-returned data never re-interpreted as code or instructions | `validation.py`, `security/untrusted.py` |
| A04 Insecure Design | Threat-modeled before implementation; least-privilege-by-default; destructive operations excluded from the MVP entirely rather than gated at runtime | `docs/threat-model.md` |
| A05 Security Misconfiguration | No network listener to misconfigure; stdio-only; no default credentials; safe defaults for all caps | `server.py`, `config.py` |
| A06 Vulnerable/Outdated Components | Pinned dependency ranges, `pip-audit` in the gate, SBOM generated | `pyproject.toml`, `sbom/cyclonedx.json` |
| A07 Identification & Auth Failures | Delegated entirely to boto3's credential provider chain / AWS IAM; no custom auth implemented | `aws_client.py` |
| A08 Software/Data Integrity Failures | Dependencies pinned by range in lockfile; no dynamic code loading | `pyproject.toml`, `uv.lock` |
| A09 Security Logging/Monitoring Failures | Structured JSON logs to stderr with redaction; AWS `ClientError` codes logged server-side for diagnosis | `logging_config.py`, `errors.py` |
| A10 SSRF | Eliminated by absence -- no HTTP client beyond boto3/botocore, no URL-shaped tool parameter | `tests/security/test_private_network_blocked.py` |

API-specific (OWASP API Security Top 10): API4:2023 Unrestricted Resource
Consumption is addressed directly via `pagination.py` and the
`max_time_range_days`/`max_results_per_page`/`max_result_pages` caps in
`config.py`.

## CWE Top 25 (selected, applicable entries)

- **CWE-20 Improper Input Validation** -- every external field validated in `validation.py`.
- **CWE-78 OS Command Injection** -- no subprocess/shell execution exists in the application (`tests/security/test_no_arbitrary_code_execution.py`).
- **CWE-22 Path Traversal** -- no filesystem tool exists (`tests/security/test_path_traversal_blocked.py`).
- **CWE-798 Use of Hard-coded Credentials** -- none present; regression-tested (`tests/security/test_no_hardcoded_credentials.py`).
- **CWE-209 Information Exposure Through an Error Message** -- `errors.py` centralizes safe error mapping.
- **CWE-400 Uncontrolled Resource Consumption** -- pagination/result/time-range caps (`pagination.py`, `validation.py`).
- **CWE-284 Improper Access Control** -- least-privilege IAM policy; no privilege-escalation path exists in the codebase.
- **CWE-918 SSRF** -- no HTTP client/URL parameter exists (`tests/security/test_private_network_blocked.py`).

## NIST SSDF (Secure Software Development Framework)

- **PO (Prepare the Organization)**: threat model authored before implementation (`docs/threat-model.md`).
- **PS (Protect the Software)**: dependency pinning, SBOM, secret scanning (`pyproject.toml`, `sbom/`, `.secrets.baseline`).
- **PW (Produce Well-Secured Software)**: input validation, least-privilege design, static analysis (ruff, bandit, mypy) in the gate.
- **RV (Respond to Vulnerabilities)**: `pip-audit` run in the gate; process for adding a regression test per discovered issue (see `docs/security-testing.md`).

## AWS Well-Architected Security Pillar / IAM least privilege

- Read-only, single-purpose IAM policy with no wildcard actions (`iam/read-only-policy.json`).
- Credentials sourced exclusively from the standard AWS provider chain -- no custom storage.
- Optional cross-account access uses `AssumeRole` with a fixed role ARN and supports `ExternalId`, per AWS's documented cross-account pattern (`iam/assume-role-trust-policy.example.json`).

## MCP-specific controls

- **Tool descriptions** state read-only status, the exact AWS API called, and what is returned (see each `@mcp.tool()` docstring in `server.py`).
- **No confused deputy**: the cross-account role is fixed server-side, never accepted as tool input (T7 in the threat model).
- **No excessive tool permissions**: 6 tools total, all read-only, verified by a live-registry test (`tests/security/test_destructive_aws_actions_unavailable.py`).
- **Untrusted external content**: AWS-returned strings are treated as data, never instructions (T5 in the threat model; `security/untrusted.py`).
- **No unexpected tool chaining risk**: each tool makes exactly one bounded AWS API call sequence; tools do not call each other or trigger side effects.

## What this codebase deliberately does NOT claim

- Not "penetration tested" -- see `docs/security-report.md`.
- Not "OWASP compliant" or "certified" -- the above is a control mapping, not a certification.
- Not hardened against a compromised AWS credential with permissions *beyond* what `iam/read-only-policy.json` grants -- that is an AWS account configuration responsibility outside this codebase's control.
