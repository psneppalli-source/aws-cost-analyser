# Security Report

**Automated security checks completed. Independent penetration testing has
not yet been performed.** Do not describe this software as
"penetration-tested," "OWASP compliant," or "certified" based on this
report -- it documents automated checks only.

Generated for `aws-cost-analyser` v0.1.0, on Windows 11, Python 3.13.14
(venv resolved to CPython 3.12.12 by `uv`), from a from-scratch build with
no prior codebase.

## Threat model summary

See [`threat-model.md`](threat-model.md) in full. 12 threats identified
(T1-T12) across malicious/compromised MCP clients, malicious AWS resource
metadata (prompt injection), supply-chain, credential exposure, DoS, and
privilege-escalation vectors. Every threat has an assigned mitigation and
an automated regression test, except T12 (container hardening), which is
covered by Dockerfile review only -- see the Container scan section below
for why the automated scan did not run.

## Security architecture

See [`architecture.md`](architecture.md). Single-hop data flow: MCP client
(stdio) → this server → AWS Cost Explorer/STS. No network listener, no
database, no third-party service, no telemetry.

## IAM model

See [`aws-permissions.md`](aws-permissions.md). Read-only policy: 6
actions (`ce:GetCostAndUsage`, `ce:GetCostForecast`, `ce:GetAnomalies`,
`ce:GetDimensionValues`, `ce:GetTags`, `sts:GetCallerIdentity`), no
wildcard actions, no other services. `Resource: "*"` is required and
documented as an AWS API limitation, not a scoping gap.

## Data-flow model / trust boundaries

See "Trust boundaries" in [`architecture.md`](architecture.md): (1)
MCP client ↔ server, (2) server ↔ AWS, (3) AWS response data ↔ server
logic (the untrusted-data boundary, T5).

## Security controls

See [`security.md`](security.md) for the full OWASP/CWE/NIST/AWS mapping.

## Test results (actual, run in this environment)

Command: `uv run pytest tests/unit tests/security -v`

```
121 passed, 1 warning in 6.52s
```

The 1 warning is `pydantic_settings`'s own `IncompleteFieldDefinitionWarning`
about the `mcp` library's internal `lifespan` field -- it originates
inside the `mcp` dependency, not this codebase, and does not affect test
outcomes.

Breakdown: 62 unit tests (`tests/unit/`) covering validation, redaction,
untrusted-data handling, error mapping, config, and every tool against
`botocore.stub.Stubber`-mocked AWS responses; 59 security regression tests
(`tests/security/`) covering the section-31 checklist (hardcoded
credentials, credential logging, header redaction, path traversal,
SSRF/metadata-endpoint, arbitrary code execution, IAM least privilege,
destructive-action absence, untrusted-metadata handling, ARN/region
validation, pagination/DoS bounds, and safe error messages).

## Static analysis

| Tool | Command | Result |
|---|---|---|
| ruff (lint) | `uv run ruff check .` | **PASS** -- All checks passed |
| bandit (SAST) | `uv run bandit -r src` | **PASS** -- 0 issues (924 lines scanned, 0 Low/Medium/High) |
| mypy (types, `--strict`) | `uv run mypy src` | **PASS** -- no issues in 18 source files |

## Dependency scan

Command: `uv run pip-audit --skip-editable`

```
No known vulnerabilities found
Name              Skip Reason
----------------- -------------------------------
aws-cost-analyser distribution marked as editable
```

The only skipped entry is this project's own editable install, which is
not a third-party dependency. **Result: PASS.**

An SBOM was generated at [`sbom/cyclonedx.json`](../sbom/cyclonedx.json)
via `cyclonedx-py environment .venv` (CycloneDX JSON format). It covers
the full development environment (runtime + dev-tooling dependencies);
regenerate with `--skip-editable`-equivalent filtering for a
production/runtime-only SBOM if required for a formal audit.

## Secret scan

Command: `uv run detect-secrets scan`

```json
"results": {}
```

No secrets detected. A baseline is committed at
[`.secrets.baseline`](../.secrets.baseline) for future incremental scans
(`detect-secrets scan --baseline .secrets.baseline`). **Result: PASS.**

**Tool substitution note**: `gitleaks` was specified in the brief but is
not installed in this environment; `detect-secrets` (also explicitly
listed as an acceptable alternative in the brief) was used instead. Both
tools scan for the same class of findings (AWS keys, private keys, high-
entropy strings, provider-specific tokens); no scan was skipped.

## Container scan

**Not run.** `docker info` in this environment shows the Docker daemon
(Docker Desktop) is not running, so neither `docker build` nor a
`trivy image` / `grype` scan could be executed here. The `Dockerfile` was
reviewed manually against the checklist in `docs/security-testing.md`
(non-root user, no secrets baked in, minimal base image, no `EXPOSE`d
port) but has **not** been built or scanned. The base image is pinned to
the `python:3.13-slim` tag rather than a verified sha256 digest for the
same reason (no reachable daemon to pull and capture a real digest) -- see
the `NOTE` comment in the `Dockerfile`.

**Before production use**: run `docker build -t aws-cost-analyser .` then
`docker run --rm aquasec/trivy image aws-cost-analyser` (or `grype`) with
Docker Desktop running, and pin the base image to the digest that scan
resolves.

## Known limitations

1. Container image has not been built or scanned in this environment (see above).
2. `mypy_boto3_ce`/`mypy_boto3_sts` type stubs are a dev-only dependency; they don't affect runtime behavior but do pin this project's type-checking to whatever Cost Explorer/STS API shape those stubs currently model.
3. SBOM covers the dev environment, not a minimal runtime-only image.
4. No live AWS account was available in this environment, so tool calls have been verified against `botocore.stub.Stubber`-simulated responses only, not a real Cost Explorer account. The request/response shapes used in tests match the real AWS API schemas (validated by Stubber's own shape validation against the actual `botocore` service model).
5. This repository is not yet a git repository in this environment, so git-history-based tooling (e.g. `git log`-aware secret scanners) had nothing to scan beyond the working tree; `detect-secrets` fell back to a filesystem walk, which still covers every file.

## Residual risks

- **T5 (prompt injection via AWS resource metadata)**: mitigated on this server's side (data is never re-interpreted), but whether a *downstream* LLM client acts on adversarial text it reads back is outside this server's control -- see the threat model's residual-risk note.
- **Operator misconfiguration**: if an operator attaches a broader-than-documented IAM policy to the identity this server uses, the least-privilege guarantees in this report no longer hold. `docs/aws-permissions.md` documents the exact minimal policy required.
- **Container hardening unverified by an automated scanner** (see above) until Docker Desktop is available to build and scan the image.

## Recommended penetration-testing scope

See "Recommended scope for an independent penetration test" in
[`security-testing.md`](security-testing.md).

## Overall summary

| Category | Result |
|---|---|
| Unit tests | PASS (62/62) |
| Security regression tests | PASS (59/59) |
| Static analysis (ruff, bandit, mypy --strict) | PASS |
| Dependency scan (pip-audit) | PASS |
| Secret scan (detect-secrets) | PASS |
| Container scan | **NOT RUN** (Docker daemon unavailable in this environment) |
| Penetration-test readiness | **NOT READY** -- automated checks only |

**Automated security checks completed. Independent penetration testing has
not yet been performed.**
