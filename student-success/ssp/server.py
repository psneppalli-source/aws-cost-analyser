"""Local server: the same API as Lambda, plus the static frontend.

    python -m ssp.server            # http://127.0.0.1:8080
    python -m ssp.server --tls      # https with a self-signed certificate

In AWS the frontend is served by CloudFront and the API by Lambda; this
server exists for development, tests and offline demos.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import ssl
import subprocess
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qsl, urlsplit

from . import settings
from .api import Request, handle

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'")


class Handler(BaseHTTPRequestHandler):
    server_version = "SSP"
    sys_version = ""

    def _send(self, status, headers, body):
        self.send_response(status)
        for k, v in {"X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
                     "X-Frame-Options": "DENY", "Content-Security-Policy": CSP, **headers}.items():
            self.send_header(k, v)
        if getattr(self.server, "tls", False):
            self.send_header("Strict-Transport-Security", "max-age=63072000")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _api(self):
        u = urlsplit(self.path)
        n = int(self.headers.get("Content-Length") or 0)
        if n > settings.MAX_UPLOAD_BYTES + 1024:
            return self._send(413, {"Content-Type": "application/json"}, b'{"error":"File too large"}')
        body = self.rfile.read(n) if n else b""
        req = Request(self.command, u.path, dict(parse_qsl(u.query)), {k.lower(): v for k, v in self.headers.items()},
                      body, self.client_address[0])
        self._send(*handle(req))

    def _static(self):
        path = urlsplit(self.path).path
        if path == "/config.js":
            body = "window.SSP_CONFIG = " + json.dumps({"mode": "local"}) + ";\n"
            return self._send(200, {"Content-Type": "application/javascript", "Cache-Control": "no-store"}, body.encode())
        rel = "index.html" if path in ("/", "") else path.lstrip("/")
        f = (settings.WEB_DIR / rel).resolve()
        if settings.WEB_DIR.resolve() not in f.parents or not f.is_file():
            f = settings.WEB_DIR / "index.html"  # SPA fallback
        ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
        self._send(200, {"Content-Type": ctype, "Cache-Control": "no-cache"}, f.read_bytes())

    def do_GET(self):
        self._api() if self.path.startswith("/api/") else self._static()

    def do_POST(self):
        self._api()

    def do_PATCH(self):
        self._api()

    def log_message(self, fmt, *args):
        if os.environ.get("SSP_QUIET") != "1":
            super().log_message(fmt, *args)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--tls", action="store_true", help="serve HTTPS with a self-signed certificate")
    a = ap.parse_args()
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    scheme = "http"
    if a.tls:
        cert, key = settings.LOCAL_DIR / "tls.crt", settings.LOCAL_DIR / "tls.key"
        if not cert.exists():
            settings.LOCAL_DIR.mkdir(parents=True, exist_ok=True)
            subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "365", "-subj", "/CN=localhost",
                            "-keyout", str(key), "-out", str(cert)], check=True, capture_output=True)
            os.chmod(key, 0o600)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        ctx.load_cert_chain(cert, key)
        srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
        srv.tls = True
        scheme = "https"
    print(f"Student Success Platform on {scheme}://{a.host}:{a.port}  (mode={settings.MODE})")
    srv.serve_forever()


if __name__ == "__main__":
    main()
