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
