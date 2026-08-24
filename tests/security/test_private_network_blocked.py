"""Sections 8 & 4: SSRF and the EC2/ECS metadata endpoint
(169.254.169.254).

This server never makes an outbound HTTP request to a model- or
client-supplied URL -- the only network calls it makes are boto3 calls to
fixed AWS service endpoints (Cost Explorer, STS), which boto3 itself
resolves; no tool accepts a URL parameter at all. SSRF, private-network
access, and metadata-endpoint access are therefore eliminated by absence.
This test pins that fact by asserting no HTTP-client library is imported
anywhere outside of boto3/botocore's own internals, and that no tool
parameter is URL-shaped."""

from __future__ import annotations

import ast

from tests.security._paths import iter_source_files

_FORBIDDEN_HTTP_MODULES = {"requests", "httpx", "urllib.request", "http.client", "aiohttp"}
_FORBIDDEN_PARAM_NAMES = {"url", "uri", "endpoint", "host", "webhook"}


def test_no_arbitrary_http_client_imported():
    offenders = []
    for path in iter_source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in _FORBIDDEN_HTTP_MODULES:
                        offenders.append((str(path), alias.name))
            if isinstance(node, ast.ImportFrom) and node.module in _FORBIDDEN_HTTP_MODULES:
                offenders.append((str(path), node.module))
    assert offenders == [], f"Unexpected HTTP client usage found: {offenders}"


def test_no_tool_accepts_a_url_or_host_parameter():
    offenders = []
    for path in iter_source_files():
        if "tools" not in path.parts and path.name != "server.py":
            continue
        text = path.read_text(encoding="utf-8")
        for name in _FORBIDDEN_PARAM_NAMES:
            if f"{name}:" in text:
                offenders.append((str(path), name))
    assert offenders == [], f"URL/host-shaped tool parameters found: {offenders}"


def test_169_254_169_254_never_appears_as_a_reachable_target():
    offenders = []
    for path in iter_source_files():
        if "169.254.169.254" in path.read_text(encoding="utf-8"):
            offenders.append(str(path))
    assert offenders == [], f"Metadata endpoint referenced in source: {offenders}"
