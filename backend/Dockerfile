FROM ubuntu:noble AS base

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system nonroot \
    && useradd --system -g nonroot -m nonroot

FROM ghcr.io/astral-sh/uv:0.11 AS uv

FROM base AS builder
COPY --from=uv /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_PREFERENCE=only-managed \
    UV_PYTHON_INSTALL_DIR=/python \
    UV_NO_DEV=1

RUN uv python install 3.14

WORKDIR /app
# Dependencies first, from the lockfile alone: this layer is reused until
# pyproject.toml or uv.lock changes, so a code change only reinstalls the project below.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-editable
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-editable

FROM base AS runtime
WORKDIR /app

# The repo's models/ folder (the embedding model), passed in by docker-compose.yml
# as the `models` build context. First, so its ~64 MB layer is reused until the models change.
# Owned by nonroot: Hugging Face writes some cache files owner-only (0600), and COPY keeps modes.
COPY --from=models --chown=nonroot:nonroot . /app/models
COPY --from=builder /python /python
COPY --from=builder /app/.venv /app/.venv
# Reports go to data/ relative to the working directory.
RUN mkdir -p /app/data && chown nonroot:nonroot /app/data

# HF_HUB_OFFLINE: the models are in the image, so a missing one fails instead of downloading.
ENV PATH="/app/.venv/bin:${PATH}" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MODELS_DIR=/app/models \
    HF_HUB_OFFLINE=1

USER nonroot
EXPOSE 8000

CMD ["uvicorn", "report_analyst.main:app", "--host", "0.0.0.0", "--port", "8000", "--timeout-keep-alive", "60"]
