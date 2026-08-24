# syntax=docker/dockerfile:1
#
# Multi-stage, non-root, minimal-package build. No secrets are ever baked
# into this image -- AWS credentials are supplied at `docker run` time via
# environment variables or a mounted ~/.aws directory (see README.md).

# NOTE: pin this to a specific sha256 digest in CI/production
# (`docker pull python:3.13-slim && docker inspect --format='{{index .RepoDigests 0}}' python:3.13-slim`).
# Left as a tag here because the Docker daemon was not reachable in the
# environment this image was authored in, so a digest could not be
# captured and verified -- see docs/security-report.md.
FROM python:3.13-slim AS builder

WORKDIR /build
RUN pip install --no-cache-dir uv==0.9.2

COPY pyproject.toml README.md ./
COPY src ./src

RUN uv venv /opt/venv && \
    uv pip install --python /opt/venv/bin/python --no-cache .

FROM python:3.13-slim

RUN groupadd --system appgroup && \
    useradd --system --gid appgroup --home-dir /home/appuser --create-home appuser

COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:${PATH}"

USER appuser
WORKDIR /home/appuser

# stdio transport only -- no EXPOSE, no listening port.
ENTRYPOINT ["aws-cost-analyser"]
