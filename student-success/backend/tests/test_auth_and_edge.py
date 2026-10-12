"""Forged/invalid tokens, Cognito token checks, and CloudFront (OAC) request handling."""

import base64
import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from app import auth
from app.settings import settings


def _b64(d: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=").decode()


def test_missing_and_garbage_tokens(client):
    assert client.get("/api/me").status_code == 401
    assert client.get("/api/me", headers={"X-App-Authorization": "Bearer nonsense"}).status_code == 401


def test_forged_signature_and_sub_swap(client, tokens):
    h, p, s = tokens["student.cse"].split(".")
    claims = json.loads(base64.urlsafe_b64decode(p + "=="))
    claims["sub"] = "local-admin.priya"  # try to become the administrator
    forged = f"{h}.{_b64(claims)}.{s}"
    assert client.get("/api/me", headers={"X-App-Authorization": f"Bearer {forged}"}).status_code == 401


def test_alg_none_and_expired(client):
    none = f"{_b64({'alg': 'none'})}.{_b64({'sub': 'local-admin.priya', 'exp': time.time() + 999})}."
    assert client.get("/api/me", headers={"X-App-Authorization": f"Bearer {none}"}).status_code == 401
    old = auth.issue_local("local-admin.priya", ttl=-10)
    assert client.get("/api/me", headers={"X-App-Authorization": f"Bearer {old}"}).status_code == 401


def test_browser_supplied_roles_are_ignored(client, tokens):
    # Extra headers or body fields claiming a role have no effect; roles come from server-side assignments.
    r = client.get("/api/students?dataset=real", headers={"X-App-Authorization": f"Bearer {tokens['student.cse']}",
                                                         "X-Role": "college_admin", "X-Department": "CSE"})
    assert r.status_code == 403  # still a student: no cross-student list


def test_disabled_account_is_rejected(call, client):
    new = call("sysadmin.dev", "POST", "/api/users", {"username": "leaver", "display_name": "Leaver"}).json()
    call("sysadmin.dev", "PUT", f"/api/users/{new['sub']}/roles", {"assignments": [{"role": "mentor"}], "version": new["version"]})
    tok = auth.issue_local(new["sub"])
    assert client.get("/api/me", headers={"X-App-Authorization": f"Bearer {tok}"}).status_code == 200
    cur = next(u for u in call("sysadmin.dev", "GET", "/api/users").json()["items"] if u["sub"] == new["sub"])
    call("sysadmin.dev", "PUT", f"/api/users/{new['sub']}/status", {"status": "disabled", "version": cur["version"]})
    auth.clear_principal_cache()
    assert client.get("/api/me", headers={"X-App-Authorization": f"Bearer {tok}"}).status_code == 401


@pytest.mark.skipif(not shutil.which("openssl"), reason="openssl needed to mint RSA test keys")
def test_cognito_token_validation(tmp_path, monkeypatch):
    key = tmp_path / "k.pem"
    subprocess.run(["openssl", "genrsa", "-out", str(key), "2048"], check=True, capture_output=True)
    mod = subprocess.run(["openssl", "rsa", "-in", str(key), "-noout", "-modulus"], check=True, capture_output=True, text=True).stdout
    n = int(mod.split("=")[1], 16)
    s = settings()
    monkeypatch.setattr(s, "cognito_pool_id", "eu-west-2_TEST")
    monkeypatch.setattr(s, "cognito_client_id", "client-123")
    monkeypatch.setattr(auth, "_keys", lambda force=False: {"kid1": (n, 65537)})

    def mint(**over):
        claims = {"iss": auth.issuer(), "aud": "client-123", "token_use": "id", "sub": "abc", "exp": time.time() + 300, **over}
        h, p = _b64({"alg": "RS256", "kid": "kid1"}), _b64(claims)
        (tmp_path / "m").write_bytes(f"{h}.{p}".encode())
        subprocess.run(["openssl", "dgst", "-sha256", "-sign", str(key), "-out", str(tmp_path / "s"), str(tmp_path / "m")], check=True)
        sig = base64.urlsafe_b64encode((tmp_path / "s").read_bytes()).rstrip(b"=").decode()
        return f"{h}.{p}.{sig}"

    assert auth.verify_cognito(mint())["sub"] == "abc"
    for bad, msg in [({"aud": "other-app"}, "different application"), ({"iss": "https://evil"}, "issuer"),
                     ({"token_use": "access"}, "token use"), ({"exp": time.time() - 5}, "expired")]:
        with pytest.raises(auth.AuthError, match=msg):
            auth.verify_cognito(mint(**bad))
    good = mint()
    h, p, sg = good.split(".")
    with pytest.raises(auth.AuthError, match="signature"):
        auth.verify_cognito(f"{h}.{_b64({**json.loads(base64.urlsafe_b64decode(p + '==')), 'sub': 'admin'})}.{sg}")


def test_local_demo_refused_inside_lambda(monkeypatch):
    from app.settings import Settings
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "ssp-api")
    monkeypatch.setenv("AUTH_MODE", "local-demo")
    with pytest.raises(RuntimeError, match="cognito"):
        Settings()


def test_lambda_entry_point_fails_to_start_with_local_auth(monkeypatch):
    """The API handler module itself refuses to load, so a misconfigured function serves nothing."""
    import importlib
    import sys

    from app import settings as s
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "ssp-api")
    monkeypatch.setenv("AUTH_MODE", "local-demo")
    s.settings.cache_clear()
    sys.modules.pop("lambda_api", None)
    try:
        with pytest.raises(RuntimeError, match="cognito"):
            importlib.import_module("lambda_api")
    finally:
        s.settings.cache_clear()
        sys.modules.pop("lambda_api", None)


# --------------------------------------------------------------------------- CloudFront OAC behaviour
SIGV4 = "AWS4-HMAC-SHA256 Credential=ASIAEXAMPLE/20261012/eu-west-2/lambda/aws4_request, SignedHeaders=host;x-amz-date, Signature=abc"


def test_app_token_travels_separately_from_sigv4(client, tokens):
    # CloudFront overwrites Authorization with its SigV4 signature; the app token must still work.
    r = client.get("/api/me", headers={"Authorization": SIGV4, "X-App-Authorization": f"Bearer {tokens['admin.priya']}"})
    assert r.status_code == 200
    assert r.headers["cache-control"].startswith("no-store")


def test_cognito_mode_ignores_authorization_header(client, tokens, monkeypatch):
    monkeypatch.setattr(settings(), "auth_mode", "cognito")
    r = client.get("/api/me", headers={"Authorization": f"Bearer {tokens['admin.priya']}"})
    assert r.status_code == 401


def test_write_requires_matching_payload_hash(client, tokens, monkeypatch):
    body = json.dumps({"data": {"assignments_due": 3, "assignments_submitted": 3, "logins": 9}}).encode()
    base = {"X-App-Authorization": f"Bearer {tokens['mentor.arjun']}", "Authorization": SIGV4, "Content-Type": "application/json"}
    bad = client.put("/api/students/real/CSE24002/records/lms/2026-02", content=body,
                     headers={**base, "x-amz-content-sha256": hashlib.sha256(b"tampered").hexdigest()})
    assert bad.status_code == 400 and bad.json()["error"]["code"] == "payload_hash_mismatch"
    monkeypatch.setattr(settings(), "require_payload_hash", True)
    missing = client.put("/api/students/real/CSE24002/records/lms/2026-02", content=body, headers=base)
    assert missing.status_code == 400 and missing.json()["error"]["code"] == "payload_hash_required"
    ok = client.put("/api/students/real/CSE24002/records/lms/2026-02", content=body,
                    headers={**base, "x-amz-content-sha256": hashlib.sha256(body).hexdigest()})
    assert ok.status_code == 201, ok.text


def test_lambda_function_url_event_through_mangum(tokens):
    """The API Lambda handles the Function URL (payload 2.0) event CloudFront forwards, including a signed write."""
    import lambda_api
    body = json.dumps({"data": {"assignments_due": 2, "assignments_submitted": 1, "logins": 4}})
    ev = {"version": "2.0", "routeKey": "$default", "rawPath": "/api/students/real/CSE24003/records/lms/2026-01",
          "rawQueryString": "", "headers": {"x-app-authorization": f"Bearer {tokens['mentor.arjun']}", "authorization": SIGV4,
                                            "content-type": "application/json", "host": "abc.lambda-url.eu-west-2.on.aws",
                                            "x-amz-content-sha256": hashlib.sha256(body.encode()).hexdigest()},
          "requestContext": {"http": {"method": "PUT", "path": "/api/students/real/CSE24003/records/lms/2026-01",
                                      "sourceIp": "1.2.3.4", "protocol": "HTTP/1.1", "userAgent": "Amazon CloudFront"},
                             "domainName": "abc.lambda-url.eu-west-2.on.aws", "stage": "$default", "requestId": "r1",
                             "accountId": "anonymous", "apiId": "abc", "timeEpoch": 0, "time": "12/Oct/2026:10:00:00 +0000"},
          "body": body, "isBase64Encoded": False}
    r = lambda_api.handler(ev, type("Ctx", (), {"aws_request_id": "r1"})())
    assert r["statusCode"] == 201, r
    assert r["headers"]["cache-control"].startswith("no-store")


def test_web_lambda_serves_spa_with_headers(tmp_path, monkeypatch):
    import importlib
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>")
    (dist / "main-ABC123.js").write_text("console.log(1)")
    monkeypatch.setenv("WEB_ROOT", str(dist))
    monkeypatch.setenv("APP_CONFIG", json.dumps({"mode": "cognito", "clientId": "x"}))
    web = importlib.import_module("web_handler")
    importlib.reload(web)

    def get(path):
        return web.handler({"rawPath": path, "requestContext": {"http": {"method": "GET"}}, "headers": {}}, None)
    r = get("/")
    assert r["statusCode"] == 200 and "app" in r["body"] and r["headers"]["Cache-Control"] == "no-cache"
    assert get("/main-ABC123.js")["headers"]["Cache-Control"].startswith("public, max-age=31536000")
    assert get("/students/real/CSE24001")["body"] == "<html>app</html>"  # SPA deep link
    assert json.loads(get("/config.json")["body"])["clientId"] == "x"
    assert get("/../../etc/passwd")["statusCode"] in (200, 404) and "root:" not in get("/../../etc/passwd")["body"]
    assert "Content-Security-Policy" in r["headers"]


def test_direct_edge_mode_serves_web_and_api_from_one_function(tmp_path, monkeypatch):
    """Temporary no-CloudFront mode: non-/api paths go to the web handler, /api to FastAPI."""
    import importlib
    import sys
    (tmp_path / "index.html").write_text("<!doctype html><app-root></app-root>")
    monkeypatch.setenv("SERVE_WEB", "1")
    monkeypatch.setenv("WEB_ROOT", str(tmp_path))
    for m in ("lambda_api", "web_handler"):
        sys.modules.pop(m, None)
    lam = importlib.import_module("lambda_api")
    try:
        def ev(path):
            return {"version": "2.0", "rawPath": path, "rawQueryString": "", "headers": {"host": "x.lambda-url.eu-west-2.on.aws"},
                    "requestContext": {"http": {"method": "GET", "path": path, "sourceIp": "1.2.3.4", "protocol": "HTTP/1.1",
                                                "userAgent": "t"}, "domainName": "x", "requestId": "r", "stage": "$default"},
                    "isBase64Encoded": False}
        page = lam.handler(ev("/students/real/CSE24001"), None)
        assert page["statusCode"] == 200 and "<app-root>" in page["body"] and "Content-Security-Policy" in page["headers"]
        api = lam.handler(ev("/api/me"), None)
        assert api["statusCode"] == 401
    finally:
        for m in ("lambda_api", "web_handler"):
            sys.modules.pop(m, None)
