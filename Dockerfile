# ReFrame — production image. uv-based; runs uvicorn. In the default compose
# stack it sits behind Caddy (see docker-compose.yml + Caddyfile).
FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

# opencv-python-headless still needs libglib at runtime, even with no GUI.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Compile bytecode and copy packages into the venv (rather than symlinking
# from the uv cache, which doesn't survive the build).
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Dependency layer — cached unless pyproject.toml / uv.lock change. The app
# itself runs from source (cwd /app), so the project package isn't installed.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN chmod +x docker-entrypoint.sh

# The venv's bin on PATH so `uvicorn` / `python` resolve to it. DATA_ROOT is
# a volume mount in compose; the entrypoint seeds it on first run.
ENV PATH="/app/.venv/bin:$PATH" \
    DATA_ROOT=/data

EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
