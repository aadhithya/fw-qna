# The app image: what `make ingest` and `make chat` run. Tests use Dockerfile.dev instead.
FROM python:3.13-slim

# git is needed to read a release tag from a clone or a git URL.
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && apt-get clean && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN uv pip install --system --no-cache .

ENV FW_QNA_HOME=/data
ENTRYPOINT ["fw-qna"]
