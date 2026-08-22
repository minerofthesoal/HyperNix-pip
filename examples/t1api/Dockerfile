# HyperNix T1 API — production image.
#
# Two stages so the runtime image carries no build toolchain, and a
# non-root user because nothing here needs root: the API reads its
# registry data, writes module blobs and a database, and serves HTTP.
#
#   docker build -f examples/t1api/Dockerfile -t hypernix-t1api .
#   docker run --rm -p 8000:8000 --env-file .env hypernix-t1api

# --- build -----------------------------------------------------------------
FROM python:3.12-slim AS build

WORKDIR /build
RUN python -m pip install --no-cache-dir --upgrade pip build

COPY pyproject.toml setup.py setup.cfg MANIFEST.in README.md LICENSE ./
COPY src ./src
RUN python -m build --wheel --outdir /dist

# --- runtime ---------------------------------------------------------------
FROM python:3.12-slim AS runtime

# torch is a base hypernix dependency but the T1 API never touches it, so
# the CPU wheel keeps the image from pulling ~2GB of CUDA runtime for a
# process that only serves HTTP.
RUN python -m pip install --no-cache-dir --upgrade pip \
 && python -m pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch

COPY --from=build /dist/*.whl /tmp/
# [t1api]    the HTTP layer (fastapi, uvicorn, pydantic)
# [t1api-pg] psycopg, for T1_DATABASE_URL
# [security] cryptography, so Keymaster encrypts keys at rest rather than
#            falling back to plain JSON with a warning
RUN python -m pip install --no-cache-dir "$(ls /tmp/*.whl)[t1api,t1api-pg,security]" \
 && rm -f /tmp/*.whl

RUN useradd --create-home --uid 10001 hypernix \
 && mkdir -p /var/lib/hypernix/modules /etc/hypernix \
 && chown -R hypernix:hypernix /var/lib/hypernix

USER hypernix
WORKDIR /var/lib/hypernix

ENV T1_ENVIRONMENT=production \
    T1_DB_PATH=/var/lib/hypernix/t1api.sqlite3 \
    T1_MODULE_STORAGE_DIR=/var/lib/hypernix/modules \
    PYTHONUNBUFFERED=1

EXPOSE 8000

# /health is the one endpoint that touches no database and is exempt from
# mTLS, precisely so it can be used for this.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"

# --factory because create_app() reads configuration at call time; a
# module-level app object would freeze the environment at import.
CMD ["python", "-m", "uvicorn", "hypernix.t1api.app:create_app", \
     "--factory", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--forwarded-allow-ips", "*"]
