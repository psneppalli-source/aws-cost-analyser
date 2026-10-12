"""API Lambda entry point: FastAPI behind a Lambda Function URL via Mangum.

With SERVE_WEB=1 (the template's temporary "direct" edge mode, no CloudFront) the same function also serves
the compiled web app for every non-/api path, so the app and API share one origin.
"""

import os

from mangum import Mangum

from app.main import app
from app.settings import settings

# Validate configuration at cold start: inside Lambda anything but Cognito authentication raises here,
# so a misconfigured function fails to initialise and serves nothing (rather than failing per request).
settings()

_api = Mangum(app, lifespan="off", api_gateway_base_path="/")
_serve_web = os.environ.get("SERVE_WEB") == "1"


def handler(event, context):
    if _serve_web and not (event.get("rawPath") or "/").startswith("/api/"):
        import web_handler
        return web_handler.handler(event, context)
    return _api(event, context)
