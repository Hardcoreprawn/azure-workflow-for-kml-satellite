# ---------------------------------------------------------------------------
# Custom Docker image for Azure Functions Flex Consumption (Python 3.12)
# Includes GDAL, rasterio, and Fiona built from source for KML/raster ops.
# ---------------------------------------------------------------------------
# Stage 1: Build GDAL and Python geospatial wheels
# ---------------------------------------------------------------------------
FROM mcr.microsoft.com/azure-functions/python:4-python3.12 AS builder

# Install system dependencies for building GDAL, Fiona, rasterio
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    gdal-bin \
    libgdal-dev \
    libgeos-dev \
    libproj-dev \
    libxml2-dev \
    libxslt1-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# Set GDAL config for pip builds
ENV GDAL_CONFIG=/usr/bin/gdal-config

# Install Python dependencies into a target directory for copying
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir --target=/home/site/wwwroot/.python_packages/lib/site-packages \
    -r /tmp/requirements.txt

# ---------------------------------------------------------------------------
# Stage 2: Runtime image
# ---------------------------------------------------------------------------
FROM mcr.microsoft.com/azure-functions/python:4-python3.12

# Install only the runtime GDAL libraries (no build tools)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gdal-bin \
    libgdal34 \
    libgeos3.12.1 \
    libproj25 \
    libxml2 \
    libxslt1.1 \
    && rm -rf /var/lib/apt/lists/*

ENV AzureWebJobsScriptRoot=/home/site/wwwroot \
    AzureFunctionsJobHost__Logging__Console__IsEnabled=true \
    GDAL_DATA=/usr/share/gdal \
    PROJ_DATA=/usr/share/proj

# Copy installed Python packages from builder
COPY --from=builder /home/site/wwwroot/.python_packages /home/site/wwwroot/.python_packages

# Copy application code
COPY host.json /home/site/wwwroot/
COPY function_app.py /home/site/wwwroot/
COPY kml_satellite/ /home/site/wwwroot/kml_satellite/
