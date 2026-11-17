# CivicLens API image - shared by the `api` and `worker` compose services.
FROM python:3.13-slim

# fastembed defaults to tempfile.gettempdir()/fastembed_cache, which is not
# persisted.  Pin every model cache inside HOME so the model_cache volume keeps
# the ONNX/CLIP/Whisper/NLLB artifacts across container restarts.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    FASTEMBED_CACHE_PATH=/home/civiclens/.cache/fastembed \
    HF_HOME=/home/civiclens/.cache/huggingface \
    HOME=/home/civiclens

# curl is used by the container healthcheck.  libgomp1 is required by the
# scikit-learn/xgboost ARM64 wheels on Debian slim.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl libgomp1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /srv/civiclens

# Install dependencies first so source changes don't invalidate the layer.
COPY pyproject.toml ./
RUN pip install .

# Application source.
COPY app ./app
COPY scripts ./scripts

RUN useradd --create-home --uid 10001 civiclens \
    && mkdir -p /home/civiclens/.cache /srv/civiclens/var/models /srv/civiclens/var/media \
    && chown -R civiclens:civiclens /home/civiclens /srv/civiclens
USER civiclens

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=5s --retries=5 --start-period=10s \
    CMD curl -fsS http://localhost:8000/health || exit 1

# The image is shared by the API and the Celery worker; the compose file and
# render.yaml override the command per service.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
