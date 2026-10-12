"""Local development server: the API plus the compiled Angular app on one port.

    python -m app.seed                     # once: load the labelled demo dataset
    python local_server.py                 # http://127.0.0.1:8000

Runs in local-demo authentication mode with SQLite storage by default. This file is
never packaged for AWS; the Lambda handlers are lambda_api.py and web_handler.py.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

os.environ.setdefault("AUTH_MODE", "local-demo")
os.environ.setdefault("STORAGE", "sqlite")
os.environ.setdefault("LOCAL_DEMO_SECRET", "local-only-" + os.urandom(8).hex())

from fastapi.responses import FileResponse, JSONResponse, Response  # noqa: E402

from app.main import app  # noqa: E402
from app.settings import settings  # noqa: E402

WEB = Path(os.environ.get("WEB_ROOT", Path(__file__).resolve().parents[1] / "frontend" / "dist" / "campus" / "browser"))


@app.get("/config.json", include_in_schema=False)
def config():
    return JSONResponse({"mode": settings().auth_mode}, headers={"Cache-Control": "no-store"})


@app.get("/{path:path}", include_in_schema=False)
def static(path: str):
    if path.startswith("api/"):
        return JSONResponse({"error": {"code": "not_found", "message": "Not found", "details": None}}, status_code=404)
    f = (WEB / path).resolve()
    if path and f.is_file() and WEB.resolve() in f.parents:
        return FileResponse(f)
    index = WEB / "index.html"
    if not index.exists():
        return Response("Build the frontend first: cd frontend && npm run build", media_type="text/plain", status_code=503)
    return FileResponse(index, headers={"Cache-Control": "no-cache"})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=os.environ.get("HOST", "127.0.0.1"), port=int(os.environ.get("PORT", "8000")), log_level="warning")
