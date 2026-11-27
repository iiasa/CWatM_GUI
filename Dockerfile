# CWatM headless execution image - for running the model remotely (e.g. via the
# IIASA Accelerator's job-dispatch API), independent of the PySide6 desktop GUI.
#
# Runs the exact same no-Qt entry point the GUI's own subprocess run uses from
# source (see CLAUDE.md "CWatM Integration" / cwatm_model.py), so behaviour here
# matches a local run byte-for-byte: same warning filters, same stdout marker
# protocol (harmless when nothing is watching for it - just extra log lines).
#
# Build:  docker build -t cwatm-model .
# Run:    docker run --rm -v /path/to/settings:/data cwatm-model /data/settings.ini

FROM python:3.12-slim-bookworm

WORKDIR /app

# rasterio's compiled extension needs libexpat at runtime even though its
# wheel bundles its own GDAL (confirmed by actually running the image: it
# imports fine until rasterio, then ImportError: libexpat.so.1 - the slim
# base strips it out). No system GDAL otherwise - installing the GDAL/osgeo
# package alongside rasterio's own bundled one breaks rasterio's import (see
# requirements.txt's own note).
RUN apt-get update && apt-get install -y --no-install-recommends libexpat1 \
    && rm -rf /var/lib/apt/lists/*

# Install the model's runtime deps (its own layer, cached across code changes).
COPY requirements_docker.txt .
RUN pip install --no-cache-dir -r requirements_docker.txt

# The CWatM model package itself (the hard rule: never edit anything under
# cwatm/, only read/copy it unchanged) and the no-Qt entry point + its one
# runtime dependency (src/gui/utils/warning_filters.py, imported by
# cwatm_model_runner.py - the whole src/ tree is copied for simplicity since
# none of its __init__.py files eagerly import anything, so nothing here
# pulls in PySide6 even though it's not installed).
COPY cwatm/ ./cwatm/
COPY src/ ./src/
COPY cwatm_model.py .

ENTRYPOINT ["python", "cwatm_model.py"]
