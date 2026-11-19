# AI Query Playground

Aplicação acadêmica de Text-to-SQL para PostgreSQL. O Playground recebe perguntas em português e exibe schema, prompt, SQL, validação, resultados, duração e tokens. O frontend acompanha o processamento via SSE e vincula a trace do Langfuse.

## Instalação no Arch Linux

Em um Arch atualizado, instale Docker, Compose (2.22 ou posterior), Buildx, GNU Make e OpenSSL. O Python e o Node das aplicações são instalados nas imagens.

```sh
sudo pacman -S --needed docker docker-compose docker-buildx make openssl
sudo systemctl enable --now docker.service
docker info --format '{{.ServerVersion}}'
docker compose version
```

Se sua instalação disponibilizar o Compose como executável independente, rode `docker-compose version`. O Makefile detecta as duas formas. Se o daemon estiver ativo e o seu usuário não tiver acesso, o grupo `docker` concede privilégios equivalentes a root. Para usar essa opção nesta máquina de desenvolvimento, execute `sudo usermod -aG docker "$USER"` e entre novamente na sessão. [Docker no Arch Linux](https://wiki.archlinux.org/title/Docker)

## Primeira inicialização

Na raiz do repositório:

```sh
make setup
make up
make status
```

`make setup` cria o `.env` com segredos aleatórios e permissão `0600` se o arquivo estiver ausente. Em seguida, constrói as imagens e baixa o modelo configurado. Na primeira execução é necessário acesso à rede para imagens, dependências e modelo. Se já existir um `.env`, o arquivo é preservado. Compare os campos faltantes com [.env.example](.env.example) e preencha apenas o necessário. Preserve as credenciais associadas a bancos que já foram inicializados.

`make up` sobe frontend, backend, PostgreSQL sintético, Ollama e os seis serviços do Langfuse. O backend aguarda o PostgreSQL e o download do modelo; o frontend aguarda o backend. O serviço de inicialização `ollama-model` termina com código zero quando o modelo está instalado. Os demais serviços têm healthchecks. O Docker Compose espera essas condições antes de concluir. [Dependências no Docker Compose](https://docs.docker.com/compose/how-tos/startup-order/) · [Compose oficial do Langfuse 4.78.0](https://github.com/langfuse/langfuse/blob/v4.78.0/docker-compose.yml)

| Serviço | Endereço padrão |
| --- | --- |
| Playground | [127.0.0.1:5173](http://127.0.0.1:5173) |
| Swagger / FastAPI | [127.0.0.1:8000/docs](http://127.0.0.1:8000/docs) |
| Langfuse | [localhost:3000](http://localhost:3000) |

Para um `.env` gerado pelo setup, as variáveis `LANGFUSE_INIT_USER_EMAIL` e `LANGFUSE_INIT_USER_PASSWORD` contêm o login inicial. O Langfuse também inicializa o projeto e as chaves na primeira subida. Em instalações anteriores, use a conta existente ou siga o [guia de observabilidade](docs/observability.md). As portas podem ser alteradas no `.env` com `AI_QUERY_FRONTEND_PORT`, `AI_QUERY_API_PORT`, `LANGFUSE_PORT` e `LANGFUSE_MINIO_PORT`. Depois de alterar o projeto ou a URL pública do Langfuse, execute `make build` e `make up` para aplicar a configuração ao frontend. [Inicialização automática do Langfuse](https://langfuse.com/self-hosting/administration/headless-initialization)

### Modelo e base de dados

`OLLAMA_MODEL` controla o modelo usado por padrão. O projeto usa `qwen2.5:3b` em CPU, com aproximadamente 1,9 GB em disco para os pesos. A escolha inicial foi feita numa máquina com Core i3-1005G1, quatro CPUs lógicas, 7,5 GiB de RAM total e sem GPU utilizável. O consumo em execução inclui o contexto e as demais dependências. A primeira inferência pode levar mais tempo pelo carregamento dos pesos. [Modelo no catálogo do Ollama](https://ollama.com/library/qwen2.5:3b)

Para comparar modelos, baixe outro no mesmo Ollama depois de subir o stack:

```sh
docker compose exec ollama ollama pull qwen2.5-coder:1.5b
docker compose exec ollama ollama list
```

Use `docker-compose` se for o seu executável. O frontend lista os modelos instalados. O banco contém 100 clientes, 10 categorias, 100 produtos, 1.000 pedidos e 3.000 itens sintéticos. Configure `SEED_REFERENCE_DATE` no formato `YYYY-MM-01` **antes de inicializar um volume novo** para reproduzir o período. Quando vazio, o bootstrap usa os 12 meses completos anteriores à inicialização. Para experimentar com um ambiente separado, use um arquivo novo em um diretório existente e um `COMPOSE_PROJECT_NAME` distinto, com portas livres configuradas:

```sh
COMPOSE_PROJECT_NAME=ai-query-experimento make setup ENV_FILE=.env.experimento
```

Use o mesmo nome de projeto e `ENV_FILE` nos comandos seguintes desse ambiente. `make down` para os contêineres, e os volumes preservam os dados e os modelos.

## Operação, testes e avaliação

| Comando | Resultado |
| --- | --- |
| `make help` | Lista os comandos. |
| `make setup` | Prepara a configuração, constrói as imagens e instala o modelo. |
| `make up` | Inicia todos os serviços e aguarda a prontidão. |
| `make down` | Para os serviços e preserva contêineres e volumes. |
| `make restart` | Para e sobe novamente respeitando as dependências. |
| `make build` | Reconstrói as imagens locais. Use `make up` em seguida para aplicá-las. |
| `make logs` | Acompanha os logs. Use `make logs LOG_SERVICES="backend frontend"` para filtrar. |
| `make status` | Mostra o estado e retorna erro se algum serviço estiver ausente ou indisponível. |
| `make test` | Executa pytest com PostgreSQL e API reais e Vitest em contêineres temporários. |
| `make benchmark` | Executa perguntas versionadas com Ollama real e imprime um relatório JSON. |

O benchmark compara as linhas com consultas de referência executadas com `ai_query_reader` e mede também a classificação de perguntas ambíguas e sem resposta. O relatório inclui os modelos, a versão do prompt, a identificação do conjunto e das referências, latências, tokens disponíveis, rejeições, falhas e IDs de traces. As execuções são sequenciais e incluem a primeira chamada ao modelo. Para registrar repetições ou comparar modelos já instalados:

```sh
make benchmark > benchmark.json
make benchmark BENCHMARK_MODELS="qwen2.5:3b qwen2.5-coder:1.5b" BENCHMARK_REPEATS=2 > comparacao.json
```

Para inspecionar um problema de inicialização, use `make status` e `make logs`. Se os serviços estiverem saudáveis mas o primeiro início demorar, ajuste o tempo de espera com `make up WAIT_TIMEOUT=900`.

## API e desenvolvimento do frontend

| Endpoint | Finalidade |
| --- | --- |
| `GET /health` | Confirma acesso ao PostgreSQL com o usuário leitor. |
| `GET /api/schema` | Devolve as tabelas autorizadas, colunas, tipos e chaves. |
| `GET /api/models` | Lista as tags instaladas no Ollama e o modelo padrão. |
| `POST /api/query/generate` | Gera uma consulta candidata sem executá-la. |
| `POST /api/query` | Gera, valida e executa uma consulta com limites. |
| `POST /api/query/stream` | Transmite as etapas via SSE e encerra com o resultado. |

```sh
curl --no-buffer --fail-with-body http://127.0.0.1:5173/api/query/stream \
  -H 'Content-Type: application/json' \
  -d '{"question":"Quantos pedidos foram registrados?"}'
```

O SQLGlot permite um único `SELECT` com CTEs de leitura no catálogo autorizado. Escrita, DDL, `SELECT INTO`, múltiplas instruções, fontes externas e funções fora da lista são bloqueadas. A execução usa transação somente leitura, `statement_timeout` de 3 segundos e devolve até 100 linhas com indicação de truncamento. O prompt só é retornado à requisição que pedir `include_prompt: true`. O histórico guarda até 20 perguntas e metadados no navegador.

Para editar a interface com recarga automática, com o stack em execução, use Node.js 22.13+ ou 24 LTS e npm:

```sh
npm --prefix frontend ci
npm --prefix frontend run dev -- --port 5174 --strictPort
```

O Vite encaminha `/api` para `http://127.0.0.1:8000`. Se necessário, ajuste `AI_QUERY_API_TARGET`, `VITE_LANGFUSE_URL` e `VITE_LANGFUSE_PROJECT_ID` em `frontend/.env.local` usando [frontend/.env.example](frontend/.env.example) como referência. Use `npm --prefix frontend test` para a suíte local e `npm --prefix frontend run build` para tipar e gerar o build.

## Documentação

- [Arquitetura](docs/architecture.md)
- [Observabilidade e SSE](docs/observability.md)
- [Roadmap](docs/roadmap.md)
- [Progresso](docs/progress.md)
