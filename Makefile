# Everything that runs code runs in Docker. Nothing is installed on the host.
IMAGE  ?= fw-qna-dev
# Run as the current user so the files written to the mounted directory are yours, not root's.
DOCKER_RUN = docker run --rm -u $(shell id -u):$(shell id -g) -e HOME=/tmp -e RUFF_CACHE_DIR=/tmp/ruff \
	-v "$(CURDIR)":/app -w /app $(IMAGE)

.DEFAULT_GOAL := help
.PHONY: help image lint fmt test check hooks

help: ## show the targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-8s %s\n", $$1, $$2}'

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

check: lint test ## lint and test (what the hooks and CI run)

hooks: ## use the hooks in .githooks for this clone (worktrees share the setting)
	git config core.hooksPath .githooks
