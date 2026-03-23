# Azure Functions Python container image for TreeSight.
# No system GDAL/GEOS/PROJ required — manylinux wheels for rasterio,
# fiona, pyproj, and shapely bundle their own native libraries.

FROM mcr.microsoft.com/azure-functions/python:4-python3.12

LABEL org.opencontainers.image.source="https://github.com/Hardcoreprawn/azure-workflow-for-kml-satellite" \
      org.opencontainers.image.description="TreeSight – satellite vegetation-analysis API"

ENV AzureWebJobsScriptRoot=/home/site/wwwroot \
    AzureFunctionsJobHost__Logging__Console__IsEnabled=true

WORKDIR /home/site/wwwroot

# Install uv for fast dependency resolution
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install Python packages into system interpreter
COPY pyproject.toml ./
RUN uv export --no-dev --no-hashes > /tmp/requirements.txt && \
    uv pip install --system -r /tmp/requirements.txt && \
    rm -f /tmp/requirements.txt

# Copy application code only (no scripts/, typings/, tests/, docs/)
COPY host.json function_app.py ./
COPY treesight/ treesight/
COPY blueprints/ blueprints/
