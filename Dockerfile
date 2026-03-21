# Azure Functions Python host for local development.
# Installs Core Tools v4 + Python deps, then runs `func start`.

FROM mcr.microsoft.com/azure-functions/python:4-python3.12

ENV AzureWebJobsScriptRoot=/home/site/wwwroot \
    AzureFunctionsJobHost__Logging__Console__IsEnabled=true

WORKDIR /home/site/wwwroot

# Install system deps for GDAL/Fiona/rasterio
RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends \
        gdal-bin libgdal-dev && \
    rm -rf /var/lib/apt/lists/*

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency manifest and install into system Python
# (Azure Functions Python worker uses system interpreter, not a venv)
COPY pyproject.toml ./
RUN uv export --no-dev --no-hashes > /tmp/requirements.txt && \
    uv pip install --system -r /tmp/requirements.txt

# Copy application code
COPY host.json function_app.py ./
COPY treesight/ treesight/
COPY blueprints/ blueprints/
COPY scripts/ scripts/
COPY typings/ typings/
