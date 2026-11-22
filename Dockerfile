# The app image: what `make ingest` and `make chat` run. Tests use Dockerfile.dev instead.
FROM python:3.13-slim

# git is needed to read a release tag from a clone or a git URL.
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && apt-get clean && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv

WORKDIR /app
# The dependencies are their own layer, so a change to our code does not reinstall them.
COPY pyproject.toml ./
RUN uv pip install --system --no-cache -r pyproject.toml
COPY src ./src
RUN uv pip install --system --no-cache --no-deps .

ENV FW_QNA_HOME=/data
ENTRYPOINT ["fw-qna"]
