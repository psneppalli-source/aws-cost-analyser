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


def req(method: str, url: str, body: bytes | None = None, headers: dict | None = None):
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
    a = p.parse_args()
    out = outputs(boto("cloudformation", a.region), a.stack)
    site = out["SiteUrl"]
    print(f"Testing {site}\n")

    s, h, b = req("GET", site + "/")
    check(s == 200 and b"<app-root" in b, "web app served by the web Lambda via CloudFront")
    check("Content-Security-Policy" in h and "Strict-Transport-Security" in h, "security headers present")
    s, _, b = req("GET", site + "/config.json")
    check(s == 200 and json.loads(b).get("mode") == "cognito", "runtime config is Cognito mode")
    s, h, b = req("GET", site + "/api/health")
    check(s == 200, "API health through CloudFront", f"{s} {b[:120]!r}")
    check("no-store" in h.get("Cache-Control", "") and "Hit" not in h.get("X-Cache", ""), "API response not cached",
          f"{h.get('Cache-Control')} {h.get('X-Cache')}")
    s, _, _ = req("GET", out["ApiFunctionUrl"].rstrip("/") + "/api/health")
    check(s == 403, "direct Function URL call refused (only CloudFront may invoke)", f"got {s}")
    s, _, _ = req("GET", site + "/api/me")
    check(s == 401, "no token -> 401", f"got {s}")
    s, _, _ = write(site, "x", "POST", "/api/auth/local/login", {"username": "admin.priya"})
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
            check(s == 200 and r.get("status") == "updated", "real write through CloudFront (OAC + payload hash + app token)",
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
