"""Static web serving: app routes get the app page; missing files are real 404s (stale chunks after a deploy)."""

import importlib


def test_missing_files_are_404_and_routes_get_the_app(tmp_path, monkeypatch):
    (tmp_path / "index.html").write_text("<!doctype html><title>app</title>")
    (tmp_path / "main-ABC123.js").write_text("console.log(1)")
    monkeypatch.setenv("WEB_ROOT", str(tmp_path))
    import web_handler
    w = importlib.reload(web_handler)
    get = lambda p: w.handler({"rawPath": p, "requestContext": {"http": {"method": "GET"}}}, None)  # noqa: E731
    page = get("/students/real/CSE24001")
    assert page["statusCode"] == 200 and "text/html" in page["headers"]["Content-Type"]
    assert page["headers"]["Cache-Control"] == "no-store"
    js = get("/main-ABC123.js")
    assert js["statusCode"] == 200 and "immutable" in js["headers"]["Cache-Control"]
    assert get("/chunk-OLDBUILD.js")["statusCode"] == 404


def test_text_files_are_gzipped_when_accepted(tmp_path, monkeypatch):
    import base64, gzip
    big = "console.log('x');" * 200
    (tmp_path / "index.html").write_text("<!doctype html>")
    (tmp_path / "main-ABC123.js").write_text(big)
    monkeypatch.setenv("WEB_ROOT", str(tmp_path))
    import web_handler
    w = importlib.reload(web_handler)
    r = w.handler({"rawPath": "/main-ABC123.js", "headers": {"accept-encoding": "gzip, br"}, "requestContext": {"http": {"method": "GET"}}}, None)
    assert r["headers"]["Content-Encoding"] == "gzip" and r["isBase64Encoded"]
    assert gzip.decompress(base64.b64decode(r["body"])).decode() == big
    plain = w.handler({"rawPath": "/main-ABC123.js", "requestContext": {"http": {"method": "GET"}}}, None)
    assert "Content-Encoding" not in plain["headers"] and plain["body"] == big


def test_api_responses_are_gzipped_through_the_lambda_adapter(client, tokens):
    import base64, gzip, json as _json
    import lambda_api
    ev = {"version": "2.0", "rawPath": "/api/risk/academic", "rawQueryString": "dataset=real",
          "headers": {"host": "x", "accept-encoding": "gzip", "x-app-authorization": "Bearer " + tokens["admin.priya"]},
          "requestContext": {"http": {"method": "GET", "path": "/api/risk/academic", "sourceIp": "1.1.1.1", "protocol": "HTTP/1.1",
                                      "userAgent": "t"}, "domainName": "x", "requestId": "r", "stage": "$default"}, "isBase64Encoded": False}
    out = lambda_api.handler(ev, None)
    hdrs = {k.lower(): v for k, v in out["headers"].items()}
    assert out["statusCode"] == 200 and hdrs.get("content-encoding") == "gzip" and out["isBase64Encoded"]
    wire = base64.b64decode(out["body"])
    body = gzip.decompress(wire)
    assert _json.loads(body)["total"] > 0 and len(wire) * 4 < len(body)
