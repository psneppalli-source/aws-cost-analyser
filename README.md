# AWS Cost Analyser (MCP Server)

A read-only [Model Context Protocol](https://modelcontextprotocol.io) server
that gives an MCP client (e.g. Claude Desktop) access to AWS Cost Explorer
data: historical spend, forecasts, anomaly detection, dimension discovery,
and cost allocation tags.

**This server cannot create, modify, or delete anything in AWS.** Every
tool maps to a single read-only `ce:Get*` or `sts:GetCallerIdentity` API
call. See [`docs/aws-permissions.md`](docs/aws-permissions.md) for the
exact IAM policy required.

> **Security status**: automated security checks (tests, static analysis,
> dependency/secret/container scans) have been run against this codebase —
> see [`docs/security-report.md`](docs/security-report.md) for real
> results. **Independent penetration testing has not been performed.**
> Do not describe this software as "penetration-tested" or "certified."

## Tools

| Tool | AWS API | Purpose |
|---|---|---|
| `get_cost_and_usage` | `ce:GetCostAndUsage` | Historical spend, optionally grouped/filtered |
| `get_cost_forecast` | `ce:GetCostForecast` | AWS's predicted future spend |
| `get_cost_anomalies` | `ce:GetAnomalies` | Cost Anomaly Detection findings |
| `get_dimension_values` | `ce:GetDimensionValues` | Discover valid values for a dimension (SERVICE, REGION, ...) |
| `get_cost_tags` | `ce:GetTags` | Discover cost allocation tag keys/values |
| `get_caller_identity` | `sts:GetCallerIdentity` | Which AWS account/principal is in use |

## Requirements

- Python 3.11+
- [`uv`](https://docs.astral.sh/uv/) (recommended) or `pip`
- AWS credentials available via the standard boto3 provider chain — this
  server never reads or stores credentials itself. See
  [AWS credential setup](https://docs.aws.amazon.com/cli/latest/userguide/cli-configure-files.html).
- An IAM identity with (at minimum) the permissions in
  [`iam/read-only-policy.json`](iam/read-only-policy.json).

## Setup

```bash
uv sync
cp .env.example .env   # edit only if you need non-default caps or a cross-account role
```

## Running

```bash
uv run aws-cost-analyser
```

The server communicates over stdio only — there is no network listener, no
port, and nothing to expose remotely in this version.

### Claude Desktop configuration

Add to your MCP client config (e.g. `claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "aws-cost-analyser": {
      "command": "uv",
      "args": ["run", "--directory", "/absolute/path/to/AWS Cost Analyser", "aws-cost-analyser"],
      "env": {
        "AWS_PROFILE": "your-readonly-profile"
      }
    }
  }
}
```

### Docker

```bash
docker build -t aws-cost-analyser .
docker run --rm -i \
  --read-only --cap-drop=ALL \
  -e AWS_PROFILE \
  -v ~/.aws:/home/appuser/.aws:ro \
  aws-cost-analyser
```

No `--privileged`, no host Docker socket, and no writable host mount is
ever required.

## Configuration

All configuration is via environment variables (or `.env`, local dev only —
never commit it). See [`.env.example`](.env.example) for the full list:
credential profile selection, an optional fixed cross-account role, and
DoS/cost-control caps (max date range, max paginated results, timeouts).

## Security documentation

- [`docs/architecture.md`](docs/architecture.md) — data flow and trust boundaries
- [`docs/threat-model.md`](docs/threat-model.md) — assets, actors, attack surfaces, mitigations
- [`docs/security.md`](docs/security.md) — controls mapped to OWASP/CWE/NIST
- [`docs/security-testing.md`](docs/security-testing.md) — penetration-test checklist
- [`docs/security-report.md`](docs/security-report.md) — actual scan/test results
- [`docs/aws-permissions.md`](docs/aws-permissions.md) — IAM permission justification

## Development

```bash
uv sync --group dev
uv run pytest tests/unit tests/security -v
uv run python scripts/security_gate.py
```
