"""AWS Lambda entry point (function URL, payload format 2.0)."""

from __future__ import annotations

import base64

from .api import Request, handle

SECURITY_HEADERS = {
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
}


def handler(event, context):
    http = event.get("requestContext", {}).get("http", {})
    body = event.get("body") or ""
    raw = base64.b64decode(body) if event.get("isBase64Encoded") else body.encode()
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    req = Request(method=http.get("method", "GET"), path=event.get("rawPath", "/"),
                  query=event.get("queryStringParameters") or {}, headers=headers, body=raw,
                  ip=headers.get("cloudfront-viewer-address", http.get("sourceIp", "")).rsplit(":", 1)[0])
    status, hdrs, out = handle(req)
    text_types = ("application/json", "text/")
    is_text = any(hdrs.get("Content-Type", "").startswith(t) for t in text_types)
    return {
        "statusCode": status,
        "headers": {**SECURITY_HEADERS, **hdrs},
        "body": out.decode() if is_text else base64.b64encode(out).decode(),
        "isBase64Encoded": not is_text,
    }
