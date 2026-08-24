# Architecture

## Overview

```
 MCP client (e.g. Claude Desktop)
        │  stdio (stdin/stdout), local process, no network socket
        ▼
 aws_cost_analyser.server  (FastMCP, 6 read-only tools)
        │  validated Pydantic request model
        ▼
 aws_cost_analyser.tools.*  (one module per tool)
        │  boto3 call, internally paginated & capped
        ▼
 aws_cost_analyser.aws_client  (boto3 session: default credential chain,
        │                       optional fixed cross-account AssumeRole)
        ▼
 AWS Cost Explorer / STS API  (ce.us-east-1.amazonaws.com, sts.*.amazonaws.com)
```

Every arrow above is the complete data flow -- there is no database, no
cache service, no queue, no additional network hop, and no third-party
service (analytics, telemetry, other AI providers) anywhere in the path.

## Components

| Module | Responsibility |
|---|---|
| `server.py` | MCP tool registration (stdio transport), converts raw MCP call kwargs into validated request objects, converts every exception into a safe message |
| `validation.py` | Pydantic models: the only place external input is accepted; every field is allowlisted/bounded |
| `aws_client.py` | boto3 session/client construction; the only place credentials are touched |
| `config.py` | Non-secret settings from environment variables (caps, optional role ARN) |
| `tools/*.py` | One AWS API call (with bounded pagination) per file |
| `security/redaction.py` | Strips credential-shaped substrings from anything that becomes a log line or error message |
| `security/untrusted.py` | Neutralizes control characters and caps length on every AWS-returned string before it leaves the server |
| `errors.py` | Maps any exception to a safe, generic-by-default client-facing message |
| `logging_config.py` | stderr-only structured logging with the redaction filter attached |

## Trust boundaries

1. **MCP client ↔ server** (stdio). The client is untrusted: it may be a
   compromised or malicious MCP client, or a legitimate client relaying
   attacker-influenced instructions (prompt injection further upstream).
   Everything crossing this boundary into the server is treated as
   untrusted input and passes through `validation.py`.
2. **Server ↔ AWS**. AWS's own IAM/auth is the boundary here; the server
   presents whatever identity the credential chain resolves to (or the
   configured cross-account role) and AWS enforces the attached IAM policy
   (`iam/read-only-policy.json`).
3. **AWS response data ↔ server logic**. AWS Cost Explorer responses can
   contain third-party- or attacker-influenced strings (tag values, cost
   category names). These cross back into the server as **data**, are
   passed through `security/untrusted.py`, and are never used to select a
   code path, build a command, or get concatenated into anything
   resembling an instruction. This boundary is the primary prompt-injection
   defense -- see `docs/threat-model.md`.

## Why no network listener

The MVP only supports the MCP stdio transport: the client launches the
server as a subprocess and communicates over its stdin/stdout. There is no
`EXPOSE`d port, no HTTP server, and no `0.0.0.0` bind anywhere in this
codebase. This eliminates an entire class of remote-exposure and
authentication concerns (sections 26-27 of the security brief) by
construction rather than by configuration.

## Optional cross-account access

If `ASSUME_ROLE_ARN` is set, the server calls `sts:AssumeRole` **once**,
at process startup, using a role ARN read from server-side configuration
only. No MCP tool accepts a role ARN or account ID as input, so a
compromised or malicious client can never redirect the server to assume a
different role or pivot into a different AWS account than the operator
configured.
