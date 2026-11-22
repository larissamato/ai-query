.DEFAULT_GOAL := help

COMPOSE ?= $(shell if docker compose version >/dev/null 2>&1; then printf 'docker compose'; elif docker-compose version >/dev/null 2>&1; then printf 'docker-compose'; fi)
ENV_FILE ?= .env
WAIT_TIMEOUT ?= 600
BENCHMARK_MODELS ?=
BENCHMARK_REPEATS ?= 1
BENCHMARK_CATEGORY ?=
BENCHMARK_CASE ?=
BENCHMARK_OUTPUT ?= artifacts/benchmarks
REFERENCE_DATE ?= 2025-01-01
EXPERIMENT_SUFFIX ?=
EXPERIMENT_API_PORT ?= 8001
EXPERIMENT_FRONTEND_PORT ?= 5174
EXPERIMENT_LANGFUSE_PORT ?= 3001
EXPERIMENT_MINIO_PORT ?= 9091
LOG_SERVICES ?=

STACK = $(COMPOSE) --env-file "$(ENV_FILE)" -f compose.yaml -f compose.langfuse.yaml
TEST_STACK = $(STACK) -f compose.test.yaml
WAIT = --wait --wait-timeout $(WAIT_TIMEOUT)
DEV_STACK = $(STACK) -f compose.dev.yaml
override EXPERIMENT_PROJECT = ai-query-experimental-$(REFERENCE_DATE)$(if $(EXPERIMENT_SUFFIX),-$(EXPERIMENT_SUFFIX))
EXPERIMENT_MANIFEST = experimental_snapshot$(if $(filter 2025-01-01,$(REFERENCE_DATE)),,-$(REFERENCE_DATE)).json
EXPERIMENT_STACK = SEED_REFERENCE_DATE="$(REFERENCE_DATE)" EVALUATION_SNAPSHOT_PATH="/app/evaluation/$(EXPERIMENT_MANIFEST)" \
	AI_QUERY_API_PORT="$(EXPERIMENT_API_PORT)" AI_QUERY_FRONTEND_PORT="$(EXPERIMENT_FRONTEND_PORT)" \
	LANGFUSE_PORT="$(EXPERIMENT_LANGFUSE_PORT)" LANGFUSE_MINIO_PORT="$(EXPERIMENT_MINIO_PORT)" \
	VITE_LANGFUSE_URL="http://localhost:$(EXPERIMENT_LANGFUSE_PORT)" OLLAMA_BASE_URL=http://ollama:11434 OLLAMA_NO_CLOUD=true \
	$(STACK) -p "$(EXPERIMENT_PROJECT)"
ENSURE_ENV = sh scripts/setup-env.sh "$(ENV_FILE)"
SEED_EMPTY = exec -T postgres sh -ec 'PGPASSWORD="$$POSTGRES_PASSWORD" psql -X -h 127.0.0.1 -U "$$POSTGRES_USER" -d "$$POSTGRES_DB" -v ON_ERROR_STOP=1 --single-transaction -f /opt/ai-query/sql/seed_if_empty.sql' </dev/null
EXPERIMENT_INSPECT = $(EXPERIMENT_STACK) run --rm --no-deps -T backend python -m evaluation.snapshot --reference-date "$(REFERENCE_DATE)"

export BENCHMARK_MODELS BENCHMARK_REPEATS BENCHMARK_CATEGORY BENCHMARK_CASE BENCHMARK_OUTPUT

.PHONY: setup up down restart build rebuild dev dev-down seed seed-benchmark snapshot experiment-up experiment-down models benchmark benchmark-all logs status test help check-compose check-config check-experiment-date check-experiment

help: ## Lista os comandos disponíveis.
	@awk 'BEGIN { FS = ":.*## " } /^[a-z][a-z-]*:.*## / { printf "  make %-12s %s\n", $$1, $$2 }' $(MAKEFILE_LIST)

check-compose:
	@test -n "$(COMPOSE)" || { printf '%s\n' 'Docker Compose não encontrado. Consulte o README para instalar no Arch Linux.' >&2; exit 1; }
	@docker info --format '{{.ServerVersion}}' >/dev/null 2>&1 || { printf '%s\n' 'Docker indisponível. Verifique docker.service e seu acesso ao daemon.' >&2; exit 1; }

check-config: check-compose
	@$(STACK) config --quiet

setup: check-compose ## Cria a configuração, instala dependências nas imagens e baixa o modelo.
	@$(ENSURE_ENV)
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

rebuild: check-config ## Reconstrói as imagens locais, atualiza os contêineres e aguarda a prontidão.
	@$(STACK) up --build $(WAIT)

dev: check-config ## Inicia Vite HMR e Uvicorn reload com o código local.
	@$(DEV_STACK) up --build $(WAIT)

dev-down: check-config ## Para o stack de desenvolvimento e preserva os dados.
	@$(DEV_STACK) stop

seed: check-compose ## Inicializa ou preenche um schema sintético vazio no Playground.
	@$(ENSURE_ENV)
	@printf '%s\n' 'Alvo da seed: banco ai_query do serviço postgres no projeto Playground.'
	@$(STACK) up $(WAIT) postgres
	@$(STACK) $(SEED_EMPTY)

check-experiment-date:
	@test "$$(date -d "$(REFERENCE_DATE)" +%F 2>/dev/null)" = "$(REFERENCE_DATE)" && test "$$(printf '%s' "$(REFERENCE_DATE)" | cut -d- -f3)" = 01 || { printf '%s\n' 'REFERENCE_DATE deve ser uma data válida no formato AAAA-MM-01.' >&2; exit 1; }

	@printf '%s\n' "$(EXPERIMENT_SUFFIX)" | grep -Eq '^[a-z0-9_-]*$$' || { printf '%s\n' 'EXPERIMENT_SUFFIX aceita letras minúsculas, números, hífen e sublinhado.' >&2; exit 1; }

check-experiment: check-experiment-date check-compose
	@test -f "backend/evaluation/$(EXPERIMENT_MANIFEST)" || { printf 'Manifeste e versione o dataset em backend/evaluation/%s antes de iniciar. Consulte docs/experimental-evaluation.md.\n' "$(EXPERIMENT_MANIFEST)" >&2; exit 1; }

seed-benchmark: check-experiment ## Prepara e audita o dataset científico isolado.
	@$(ENSURE_ENV)
	@printf 'Alvo da seed científica: ai_query no projeto %s\n' "$(EXPERIMENT_PROJECT)"
	@$(EXPERIMENT_STACK) up $(WAIT) postgres
	@$(EXPERIMENT_STACK) $(SEED_EMPTY)
	@$(EXPERIMENT_STACK) build backend
	@$(EXPERIMENT_INSPECT) --verify-references

snapshot: check-experiment ## Inspeciona o banco científico em uma transação somente leitura.
	@printf 'Projeto científico: %s\n' "$(EXPERIMENT_PROJECT)"
	@$(EXPERIMENT_INSPECT)

experiment-up: seed-benchmark ## Sobe o ambiente científico e verifica PostgreSQL, Ollama e Langfuse.
	@$(EXPERIMENT_STACK) up --build $(WAIT)
	@$(EXPERIMENT_STACK) exec -T backend python -m evaluation.snapshot --reference-date "$(REFERENCE_DATE)" --check-services
	@printf 'Frontend científico: http://127.0.0.1:%s\n' "$(EXPERIMENT_FRONTEND_PORT)"

experiment-down: check-experiment-date check-compose ## Para o ambiente científico e preserva os volumes.
	@$(EXPERIMENT_STACK) stop

models: check-experiment-date check-compose ## Lista modelos e tamanhos nos serviços Ollama ativos.
	@found=0; \
	if [ -n "$$($(STACK) ps -q --status running ollama 2>/dev/null)" ]; then \
		printf '%s\n' 'Ollama do Playground'; $(STACK) exec -T ollama ollama list || exit 1; found=1; \
	fi; \
	if [ -n "$$($(EXPERIMENT_STACK) ps -q --status running ollama 2>/dev/null)" ]; then \
		printf '%s\n' 'Ollama científico ($(REFERENCE_DATE))'; $(EXPERIMENT_STACK) exec -T ollama ollama list || exit 1; found=1; \
	fi; \
	test "$$found" -eq 1 || { printf '%s\n' 'Ollama indisponível. Use make up ou make experiment-up.' >&2; exit 1; }

benchmark: ## Avalia um caso ou categoria e exporta CSV e JSON.
benchmark benchmark-all: check-experiment
	@mkdir -p -- "$$BENCHMARK_OUTPUT"
	@$(EXPERIMENT_STACK) run --rm --no-deps -T --user "$$(id -u):$$(id -g)" \
		-v "$$(realpath -- "$$BENCHMARK_OUTPUT"):/results" backend python -m evaluation.run_experiment \
		--models "$$BENCHMARK_MODELS" --repeats "$$BENCHMARK_REPEATS" --category "$$BENCHMARK_CATEGORY" \
		--case "$$BENCHMARK_CASE" --output /results --reference-date "$(REFERENCE_DATE)" $(if $(filter benchmark-all,$@),--all)

# Entrada própria no help, com a mesma receita dos dois alvos.
benchmark-all: ## Executa as 105 perguntas para os modelos locais de geração de texto.
