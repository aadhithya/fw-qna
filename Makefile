# Everything that runs code runs in Docker. Nothing is installed on the host.
SHELL := /bin/bash  # the chat target filters compose's stderr with a process substitution
IMAGE  ?= fw-qna-dev
# Run as the current user so the files written to the mounted directory are yours, not root's.
DOCKER_RUN = docker run --rm -u $(shell id -u):$(shell id -g) -e HOME=/tmp -e RUFF_CACHE_DIR=/tmp/ruff \
	-v "$(CURDIR)":/app -w /app $(IMAGE)

# The app itself: Ollama and the fw-qna commands run in Docker Compose.
COMPOSE = FW_QNA_UID=$(shell id -u) FW_QNA_GID=$(shell id -g) COMPOSE_PROFILES=tools docker compose
MODEL  ?= embeddinggemma-2:270m
SOURCE ?= https://github.com/aadhithya/featherweight.git
need-ref = $(if $(REF),,$(error REF is required, e.g. REF=v0.1.0))

.DEFAULT_GOAL := help
.PHONY: help image lint fmt test check hooks ollama-up up pull-model down ingest versions drop search eval chat check-embeddings

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

ollama-up:
	@mkdir -p "$${FW_QNA_DATA:-data}/ollama" "$${FW_QNA_DATA:-data}/fw-qna"
	$(COMPOSE) up -d --wait ollama

up: ollama-up ## start Ollama and pull the embedding model (once)
	@$(COMPOSE) exec -T ollama ollama list | grep -q "$(MODEL)" || $(MAKE) --no-print-directory pull-model

pull-model:
	@# a stale Ollama image can be too old for the model; refresh it only if the pull fails, not on every start
	@$(COMPOSE) exec -T ollama ollama pull $(MODEL) || { \
		echo "The pull failed. Refreshing the Ollama image, which may be too old for this model..."; \
		$(COMPOSE) pull ollama && $(COMPOSE) up -d --force-recreate --wait ollama \
		&& $(COMPOSE) exec -T ollama ollama pull $(MODEL); }

down: ## stop Ollama (the data stays)
	$(COMPOSE) down

ingest: up ## index a release and its skill, from GitHub: make ingest REF=v0.1.0 [SOURCE=<git url or local clone>]
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

eval: up ## measure retrieval (recall@k and MRR) over evals/retrieval.yaml; local only, no chat model
	$(COMPOSE) run --build --rm -v "$(CURDIR)/evals":/evals:ro app eval --questions /evals/retrieval.yaml

chat: ## chat about the docs (needs ANTHROPIC_API_KEY in your shell or in .env)
	@# Docker's own output is hidden (it is noise), but each step says what it is doing, and the output
	@# is shown if a step fails. The chat clears the screen itself once it is up.
	@echo "▸ Starting Ollama (the search needs it to embed your questions)"
	@$(MAKE) --no-print-directory ollama-up >/dev/null 2>&1 || { $(MAKE) --no-print-directory ollama-up; exit 1; }
	@echo "▸ Building the chat app"
	@$(COMPOSE) --progress quiet build app
	@echo "▸ Starting the chat"
	@$(COMPOSE) --progress quiet run --rm app chat 2> >(grep -v 'No services to build' >&2)

check-embeddings: up ## check that the real model gives sane vectors
	$(COMPOSE) run --build --rm -v "$(CURDIR)/scripts":/scripts:ro --entrypoint python app /scripts/check_embeddings.py
