"""Web Lambda: serves the compiled Angular app packaged inside this ZIP.

CloudFront calls this Function URL (IAM-protected, signed with OAC) for every
non-/api path. Hashed assets are cached for a year; index.html and
config.json are revalidated. Unknown paths return index.html so Angular
deep links work. Only files inside WEB_ROOT can be served.
"""

from __future__ import annotations

import base64
import gzip
import json
import mimetypes
import os
from pathlib import Path

ROOT = Path(os.environ.get("WEB_ROOT", Path(__file__).parent / "web")).resolve()
APP_CONFIG = os.environ.get("APP_CONFIG", '{"mode": "cognito"}')
SECURITY = {
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": os.environ.get(
        "CSP", "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
               f"connect-src 'self' https://*.amazoncognito.com https://cognito-idp.{os.environ.get('AWS_REGION', 'eu-west-2')}.amazonaws.com; "
               "frame-ancestors 'none'; "
               "base-uri 'self'; form-action 'self' https://*.amazoncognito.com"),
}
TEXT = ("text/", "application/javascript", "application/json", "image/svg+xml")


def _resp(status: int, body: bytes, ctype: str, cache: str, gzip_ok: bool = False) -> dict:
    is_text = ctype.startswith(TEXT)
    headers = {**SECURITY, "Content-Type": ctype, "Cache-Control": cache}
    if is_text and gzip_ok and len(body) > 1024:  # page code and styles shrink several-fold
        headers.update({"Content-Encoding": "gzip", "Vary": "Accept-Encoding"})
        return {"statusCode": status, "headers": headers, "body": base64.b64encode(gzip.compress(body, 6)).decode(),
                "isBase64Encoded": True}
    return {"statusCode": status, "headers": headers,
            "body": body.decode() if is_text else base64.b64encode(body).decode(), "isBase64Encoded": not is_text}


def handler(event, context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    if method not in ("GET", "HEAD"):
        return _resp(405, b"Method not allowed", "text/plain", "no-store")
    path = event.get("rawPath", "/")
    if path == "/config.json":
        return _resp(200, APP_CONFIG.encode(), "application/json", "no-cache")
    rel = path.lstrip("/") or "index.html"
    f = (ROOT / rel).resolve()
    if ROOT not in f.parents or not f.is_file():
        if f.suffix:  # a missing file (e.g. a chunk from an older build) is a real 404, never the app page
            return _resp(404, b"Not found", "text/plain", "no-store")
        f = ROOT / "index.html"
    if not f.is_file():
        return _resp(404, b"Not found", "text/plain", "no-store")
    ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
    if ctype == "text/html":
        ctype = "text/html; charset=utf-8"
    hashed = f.name != "index.html" and any(c == "-" for c in f.stem) and f.suffix in (".js", ".css", ".woff2")
    # the app page is never stored (by browsers, Netlify or CloudFront), so it always names the current files
    cache = "public, max-age=31536000, immutable" if hashed else "no-store" if f.name == "index.html" else "no-cache"
    accept = {k.lower(): v for k, v in (event.get("headers") or {}).items()}.get("accept-encoding", "")
    return _resp(200, f.read_bytes(), ctype, cache, gzip_ok="gzip" in accept)


if __name__ == "__main__":  # quick manual check
    print(json.dumps(handler({"rawPath": "/", "requestContext": {"http": {"method": "GET"}}}, None))[:200])
