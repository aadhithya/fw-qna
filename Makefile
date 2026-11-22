# Everything that runs code runs in Docker. Nothing is installed on the host.
IMAGE  ?= fw-qna-dev
# Run as the current user so the files written to the mounted directory are yours, not root's.
DOCKER_RUN = docker run --rm -u $(shell id -u):$(shell id -g) -e HOME=/tmp -e RUFF_CACHE_DIR=/tmp/ruff \
	-v "$(CURDIR)":/app -w /app $(IMAGE)

# The app itself: Ollama and the fw-qna commands run in Docker Compose.
COMPOSE = FW_QNA_UID=$(shell id -u) FW_QNA_GID=$(shell id -g) docker compose
MODEL  ?= embeddinggemma-2:270m
SOURCE ?= ../featherweight
need-ref = $(if $(REF),,$(error REF is required, e.g. REF=v0.1.0))

.DEFAULT_GOAL := help
.PHONY: help image lint fmt test check hooks up down ingest versions drop search check-embeddings

help: ## show the targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-17s %s\n", $$1, $$2}'

image: ## build the dev image (cached; rebuilds when pyproject.toml changes)
	@docker build -q -f Dockerfile.dev -t $(IMAGE) . >/dev/null

lint: image ## ruff check and format check
	$(DOCKER_RUN) ruff check src tests
	$(DOCKER_RUN) ruff format --check src tests

fmt: image ## ruff fix and format
	$(DOCKER_RUN) ruff check --fix src tests
	$(DOCKER_RUN) ruff format src tests

test: image ## run the tests
	$(DOCKER_RUN) pytest -q -p no:cacheprovider

check: lint test ## lint and test (what the pre-commit hooks run)

hooks: ## install the pre-commit hooks for this clone (worktrees share them)
	@git config --unset-all core.hooksPath || true
	pre-commit install

up: ## start Ollama and pull the embedding model (once)
	@mkdir -p "$${FW_QNA_DATA:-data}/ollama" "$${FW_QNA_DATA:-data}/fw-qna"
	@# a stale local image can be too old for the model, so refresh it (skipped quietly when offline)
	@$(COMPOSE) pull --quiet ollama || true
	$(COMPOSE) up -d --wait ollama
	@$(COMPOSE) exec -T ollama ollama list | grep -q "$(MODEL)" || $(COMPOSE) exec -T ollama ollama pull $(MODEL)

down: ## stop Ollama (the data stays)
	$(COMPOSE) down

ingest: up ## index a release: make ingest REF=v0.1.0 [SOURCE=../featherweight or a git URL]
	$(need-ref)
	@if echo "$(SOURCE)" | grep -qE '^(https?://|git@)'; then \
		$(COMPOSE) run --build --rm app ingest --source "$(SOURCE)" --ref $(REF); \
	else \
		$(COMPOSE) run --build --rm -v "$$(cd $(SOURCE) && pwd)":/source:ro app ingest --source /source --ref $(REF); \
	fi

versions: ## list the indexed releases
	$(COMPOSE) run --build --rm app versions

drop: ## remove a release from the index: make drop REF=v0.1.0
	$(need-ref)
	$(COMPOSE) run --build --rm app drop $(REF)

search: up ## search the docs, no chat model: make search Q="how do I define an agent" [ARGS="--keywords JobWorker"]
	$(COMPOSE) run --build --rm app search "$(Q)" $(ARGS)

check-embeddings: up ## check that the real model gives sane vectors
	$(COMPOSE) run --build --rm -v "$(CURDIR)/scripts":/scripts:ro --entrypoint python app /scripts/check_embeddings.py
