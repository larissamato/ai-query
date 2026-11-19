.DEFAULT_GOAL := help

COMPOSE ?= $(shell if docker compose version >/dev/null 2>&1; then printf 'docker compose'; elif docker-compose version >/dev/null 2>&1; then printf 'docker-compose'; fi)
ENV_FILE ?= .env
WAIT_TIMEOUT ?= 600
BENCHMARK_MODELS ?=
BENCHMARK_REPEATS ?= 1
LOG_SERVICES ?=

STACK = $(COMPOSE) --env-file "$(ENV_FILE)" -f compose.yaml -f compose.langfuse.yaml
TEST_STACK = $(STACK) -f compose.test.yaml
WAIT = --wait --wait-timeout $(WAIT_TIMEOUT)

.PHONY: setup up down restart build logs status test benchmark help check-compose check-config

help: ## Lista os comandos disponíveis.
	@awk 'BEGIN { FS = ":.*## " } /^[a-z]+:.*## / { printf "  make %-12s %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

check-compose:
	@test -n "$(COMPOSE)" || { printf '%s\n' 'Docker Compose não encontrado. Consulte o README para instalar no Arch Linux.' >&2; exit 1; }
	@docker info --format '{{.ServerVersion}}' >/dev/null 2>&1 || { printf '%s\n' 'Docker indisponível. Verifique docker.service e seu acesso ao daemon.' >&2; exit 1; }

check-config: check-compose
	@$(STACK) config --quiet

setup: check-compose ## Cria a configuração, instala dependências nas imagens e baixa o modelo.
	@sh scripts/setup-env.sh "$(ENV_FILE)"
	@$(STACK) config --quiet
	@$(STACK) build
	@$(STACK) up $(WAIT) ollama
	@$(STACK) run --rm --no-deps -T ollama-model

up: check-config ## Inicia o stack completo e aguarda os healthchecks.
	@$(STACK) up $(WAIT)

down: check-config ## Para todos os serviços, preservando contêineres e dados.
	@$(STACK) stop

restart: check-config ## Para e inicia os serviços respeitando as dependências.
	@$(STACK) stop
	@$(STACK) up $(WAIT)

build: check-config ## Reconstrói as imagens do backend e do frontend.
	@$(STACK) build

logs: check-config ## Acompanha os logs. Use LOG_SERVICES para filtrar serviços.
	@$(STACK) logs --follow --tail 100 $(LOG_SERVICES)

status: check-config ## Mostra serviços, healthchecks e a conclusão do download.
	@sh scripts/compose-status.sh $(STACK)

test: check-config ## Executa pytest e Vitest em contêineres de teste.
	@$(STACK) up $(WAIT) backend
	@$(TEST_STACK) run --rm --build --no-deps -T backend-tests
	@$(TEST_STACK) run --rm --build --no-deps -T frontend-tests

benchmark: up ## Avalia os modelos locais com perguntas versionadas e imprime JSON.
	@$(STACK) exec -T backend python -m evaluation.benchmark --models "$(BENCHMARK_MODELS)" --repeats "$(BENCHMARK_REPEATS)"
