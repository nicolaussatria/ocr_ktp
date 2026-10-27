# Card OCR API: the Gradio screen and the REST API (/v1/ocr/..., /docs) on port 7860.
# Built and started by docker-compose.yml; see docs/DEPLOYMENT.md, "Docker on your own server".
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    GRADIO_ANALYTICS_ENABLED=False \
    HF_HUB_DISABLE_TELEMETRY=1

WORKDIR /app

# OpenCV's system libraries: the same list Hugging Face Spaces installs.
COPY packages.txt .
RUN apt-get update \
    && xargs -a packages.txt apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

# The tested package set (CPython 3.12, Linux). The OCR models ship inside the rapidocr
# wheel, so nothing is downloaded when the container starts.
COPY requirements.lock .
RUN pip install -r requirements.lock

COPY THIRD_PARTY.md app.py ./
COPY card_ocr ./card_ocr
COPY scripts ./scripts
COPY examples ./examples

# The service runs as an ordinary user and cannot change its own code.
RUN useradd --create-home --uid 10001 ocr
USER ocr

# Load and checksum the models now, as the service user: a broken install fails the
# build instead of the first scan.
RUN python -m scripts.warmup

EXPOSE 7860
HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7860/readyz', timeout=8)"]
CMD ["python", "app.py", "--host", "0.0.0.0", "--port", "7860"]
