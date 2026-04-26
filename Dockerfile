# ─────────────────────────────────────────────────────────────
# Canopex Application Image
#
# Extends treesight-base (our custom slim Functions runtime)
# with application dependencies and code only.
#
# Base image: ghcr.io/<owner>/treesight-base:latest
# Built by CI on every push to main.
# ─────────────────────────────────────────────────────────────
ARG BASE_IMAGE=treesight-base:latest
FROM ${BASE_IMAGE}

ARG APP_VERSION=0.0.0-dev
ARG GIT_SHA=unknown

LABEL org.opencontainers.image.source="https://github.com/Hardcoreprawn/azure-workflow-for-kml-satellite" \
      org.opencontainers.image.description="Canopex – satellite vegetation-analysis API" \
      org.opencontainers.image.version="${APP_VERSION}" \
      org.opencontainers.image.revision="${GIT_SHA}"

ENV APP_VERSION=${APP_VERSION} \
    GIT_SHA=${GIT_SHA}

# Install uv for fast, deterministic dependency resolution
COPY --from=ghcr.io/astral-sh/uv:0.9.7 /uv /usr/local/bin/uv

# Install Python packages (production only, from lockfile)
COPY pyproject.toml uv.lock ./
RUN uv export --no-dev --no-hashes > /tmp/requirements.txt && \
    uv pip install --system -r /tmp/requirements.txt && \
    rm -f /tmp/requirements.txt /usr/local/bin/uv

# Copy application code only (no scripts/, typings/, tests/, docs/)
COPY host.json function_app.py function_registration.py ./
COPY treesight/ treesight/
COPY blueprints/ blueprints/
