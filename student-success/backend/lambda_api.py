"""API Lambda entry point: FastAPI behind a Lambda Function URL via Mangum."""

from mangum import Mangum

from app.main import app
from app.settings import settings

# Validate configuration at cold start: inside Lambda anything but Cognito authentication raises here,
# so a misconfigured function fails to initialise and serves nothing (rather than failing per request).
settings()

handler = Mangum(app, lifespan="off", api_gateway_base_path="/")
