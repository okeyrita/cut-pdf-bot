# One image, two commands: `python -m pdfbot` for the bot, `celery ... worker` for the worker.
#
# They share almost every dependency, so a single image means one build, one layer cache and no
# chance of the two drifting apart. The cost is that the bot carries the OCR toolchain it never
# uses; if the ~1 GB matters, split `runtime` into `bot` and `worker` targets and move the
# tesseract/ghostscript layer into the latter.

# --------------------------------------------------------------------------- builder
FROM python:3.14-slim-trixie AS builder

COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Dependencies first, in their own layer: they change far less often than the source, so editing a
# handler does not re-resolve 92 packages.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-install-project --no-dev

COPY src/ ./src/
COPY README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

# --------------------------------------------------------------------------- runtime
FROM python:3.14-slim-trixie AS runtime

# Debian 13 (trixie) carries tesseract 5.x and ghostscript 10.x. Every package here is a hard
# runtime requirement of ocrmypdf or the compression path -- none are build-time only:
#   tesseract-ocr[-rus|-eng]  the OCR engine and its language models
#   ghostscript               lossy compression, and ocrmypdf's PDF/A output
#   qpdf                      pikepdf's backing library
#   unpaper                   ocrmypdf --clean
#   pngquant                  ocrmypdf --optimize
RUN apt-get update && apt-get install --no-install-recommends -y \
        tesseract-ocr \
        tesseract-ocr-rus \
        tesseract-ocr-eng \
        ghostscript \
        qpdf \
        unpaper \
        pngquant \
    && rm -rf /var/lib/apt/lists/*

# Fail the build now, not on a user's first Russian scan, if a language model is missing.
RUN tesseract --list-langs 2>&1 | grep -qx rus \
    && tesseract --list-langs 2>&1 | grep -qx eng \
    && gs --version

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DATA_DIR=/data

RUN groupadd --system app && useradd --system --gid app --home /app app

WORKDIR /app
COPY --from=builder --chown=app:app /app/.venv /app/.venv
COPY --chown=app:app src/ ./src/

RUN mkdir -p /data/jobs && chown -R app:app /data
VOLUME ["/data"]

USER app

# Cheap liveness signal: the package imports and settings validate.
HEALTHCHECK --interval=60s --timeout=10s --start-period=20s --retries=3 \
    CMD python -c "from pdfbot.config import get_settings; get_settings()" || exit 1

CMD ["python", "-m", "pdfbot"]
