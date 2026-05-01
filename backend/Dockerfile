FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app/backend

ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy

COPY README.md /app/README.md
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --extra bluesky --extra ai --extra eval --no-dev --frozen

COPY backend/app ./app

EXPOSE 8000

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
