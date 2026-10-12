"""Smoke test a deployment through CloudFront, including real write requests.

    python infra/smoke_test.py --token <Cognito ID token of a mentor test account, e.g. mentor.arjun>

Copy the token from the browser after signing in (sessionStorage 'ssp.session' -> idToken). Checks:
  web app and security headers; /config.json in Cognito mode; API health through CloudFront;
  direct Function URL calls refused (IAM); no token -> 401; local demo sign-in absent;
  a real PUT through CloudFront (OAC SigV4 + payload hash + separate app token) and its restore;
  a wrong payload hash rejected; API responses never cached.
Writes touch only the synthetic demo dataset and are restored.
"""

from __future__ import annotations

import hashlib
import json
import sys
import urllib.error
import urllib.request

from common import boto, outputs, parser

failures = []
INVOKE: dict = {}  # set by --via-invoke: {"client": lambda client, "function": name}


def _invoke(method: str, url: str, body: bytes | None, headers: dict | None):
    """Send a Function URL (payload v2) event through the Lambda API instead of HTTP."""
    import base64
    from urllib.parse import urlsplit
    u = urlsplit(url)
    ev = {"version": "2.0", "rawPath": u.path or "/", "rawQueryString": u.query,
          "headers": {"host": u.netloc, **{k.lower(): v for k, v in (headers or {}).items()}},
          "requestContext": {"http": {"method": method, "path": u.path or "/", "sourceIp": "203.0.113.1", "protocol": "HTTP/1.1",
                                      "userAgent": "smoke-test"}, "domainName": u.netloc, "requestId": "smoke", "stage": "$default"},
          "body": base64.b64encode(body).decode() if body else None, "isBase64Encoded": bool(body)}
    r = INVOKE["client"].invoke(FunctionName=INVOKE["function"], Payload=json.dumps(ev).encode())
    out = json.loads(r["Payload"].read())
    if "statusCode" not in out:
        return 502, {}, json.dumps(out).encode()
    b = out.get("body") or ""
    data = base64.b64decode(b) if out.get("isBase64Encoded") else b.encode()
    hdrs = {k.title(): v for k, v in (out.get("headers") or {}).items()}
    return out["statusCode"], hdrs, data


def req(method: str, url: str, body: bytes | None = None, headers: dict | None = None):
    if INVOKE:
        return _invoke(method, url, body, headers)
    r = urllib.request.Request(url, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def check(ok: bool, what: str, detail: str = "") -> None:
    print(("PASS " if ok else "FAIL ") + what + (f" — {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(what)


def write(site: str, token: str, method: str, path: str, payload: dict, bad_hash: bool = False):
    body = json.dumps(payload, separators=(",", ":")).encode()
    h = {"Content-Type": "application/json", "X-App-Authorization": f"Bearer {token}",
         "x-amz-content-sha256": "0" * 64 if bad_hash else hashlib.sha256(body).hexdigest()}
    s, _, b = req(method, site + path, body, h)
    return s, (json.loads(b) if b[:1] in (b"{", b"[") else b)


def main() -> int:
    p = parser("Smoke test through CloudFront")
    p.add_argument("--token", help="Cognito ID token for a mentor test account (enables write tests)")
    p.add_argument("--student", default="CSE24001", help="demo student the mentor may edit (default: first CSE year 3)")
    p.add_argument("--via-invoke", action="store_true",
                   help="call the API function through the Lambda API (for networks that block the site's host); "
                        "skips edge-only checks")
    a = p.parse_args()
    out = outputs(boto("cloudformation", a.region), a.stack)
    if a.via_invoke:
        INVOKE.update(client=boto("lambda", a.region), function=out["ApiFunctionName"])
        print("Mode: Lambda invoke with Function URL events (edge checks skipped)")
    site = out["SiteUrl"]
    print(f"Testing {site}\n")

    if not (a.via_invoke and out.get("EdgeMode") != "direct"):  # in cloudfront mode the web app is another function
        s, h, b = req("GET", site + "/")
        check(s == 200 and b"<app-root" in b, "web app served")
        check("Content-Security-Policy" in h and "Strict-Transport-Security" in h, "security headers present")
        s, _, b = req("GET", site + "/config.json")
        check(s == 200 and json.loads(b).get("mode") == "cognito", "runtime config is Cognito mode")
    s, h, b = req("GET", site + "/api/health")
    check(s == 200, "API health", f"{s} {b[:120]!r}")
    check("no-store" in h.get("Cache-Control", "") and "Hit" not in h.get("X-Cache", ""), "API response not cached",
          f"{h.get('Cache-Control')} {h.get('X-Cache')}")
    if a.via_invoke:
        pass
    elif out.get("EdgeMode", "cloudfront") == "cloudfront":
        s, _, _ = req("GET", out["ApiFunctionUrl"].rstrip("/") + "/api/health")
        check(s == 403, "direct Function URL call refused (only CloudFront may invoke)", f"got {s}")
    else:
        print("INFO direct edge mode (temporary): no CloudFront; the function URL is the public site")
    s, _, _ = req("GET", site + "/api/me")
    check(s == 401, "no token -> 401", f"got {s}")
    s, _ = write(site, "x", "POST", "/api/auth/local/login", {"username": "admin.priya"})
    check(s == 404, "local demo sign-in endpoint absent", f"got {s}")

    if a.token:
        auth = {"X-App-Authorization": f"Bearer {a.token}"}
        s, _, b = req("GET", site + "/api/me", headers=auth)
        check(s == 200, "token accepted (signature, issuer, audience, expiry, token_use)", f"{s} {b[:200]!r}")
        path = f"/api/students/demo/{a.student}/records/lms/2026-09"
        s, _, b = req("GET", site + f"/api/students/demo/{a.student}/records?category=lms&period=2026-09", headers=auth)
        items = json.loads(b).get("items", []) if s == 200 else []
        check(bool(items), "read a demo record", f"{s} {b[:200]!r}")
        if items:
            cur = items[0]
            orig = {k: cur[k] for k in ("assignments_due", "assignments_submitted", "logins")}
            s, r = write(site, a.token, "PUT", path, {"data": {**orig, "logins": orig["logins"] + 1}, "version": cur["version"]})
            check(s == 200 and r.get("status") == "updated", "real write (payload hash + app token; via CloudFront OAC in cloudfront mode)",
                  f"{s} {str(r)[:200]}")
            if s == 200:
                s2, r2 = write(site, a.token, "PUT", path, {"data": orig, "version": r["record"]["version"]})
                check(s2 == 200, "write restored")
            s, r = write(site, a.token, "PUT", path, {"data": orig, "version": 1}, bad_hash=True)
            check(s in (400, 403), "wrong payload hash rejected", f"got {s}")
    else:
        print("SKIP write tests (pass --token)")
    print(f"\n{'FAILED: ' + ', '.join(failures) if failures else 'All smoke tests passed.'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
