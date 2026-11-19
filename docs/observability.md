# Observabilidade local

O projeto usa Langfuse **4.78.0** em Docker Compose. O arquivo complementar sobe o serviço web, o worker, PostgreSQL 17, ClickHouse, Redis 7 e MinIO. O PostgreSQL do Langfuse tem volume e credenciais próprios. Web e MinIO são acessíveis pelo loopback. Os demais serviços usam a rede interna do Compose. O AI Gateway é opcional na distribuição oficial e o pipeline usa o Ollama diretamente. [Compose oficial da versão 4.78.0](https://github.com/langfuse/langfuse/blob/v4.78.0/docker-compose.yml) · [Guia oficial de instalação local](https://langfuse.com/self-hosting/deployment/docker-compose)

## Iniciar e configurar

Em instalações novas, execute `make setup` e `make up`. O setup cria um arquivo de configuração apenas se estiver ausente. Nele, `LANGFUSE_INIT_USER_EMAIL` e `LANGFUSE_INIT_USER_PASSWORD` contêm o login inicial. O Langfuse usa a configuração do projeto e das chaves na primeira subida. Abra `http://localhost:3000` e entre com essas credenciais.

Se o arquivo existente não tiver os dados de inicialização e você ainda não tiver uma conta, use **Sign up** para criar o usuário local, a organização e o projeto. Na página de **API Keys** do projeto, crie as chaves e preencha `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY` e `VITE_LANGFUSE_PROJECT_ID` no arquivo local. Execute `make build` e `make up` para aplicar essas configurações.

Para executar a API pelo host, forneça `LANGFUSE_BASE_URL=http://localhost:3000` e as duas chaves no ambiente do processo. O [README](../README.md) descreve as portas configuráveis e os comandos de operação.

## Localizar e interpretar uma trace

Envie uma pergunta por `POST /api/query` e copie o `trace_id` do JSON ou o cabeçalho `X-Trace-Id`. No projeto Langfuse, abra **Tracing** e localize o ID da trace. Com o ID do projeto da URL, também é possível abrir `http://localhost:3000/project/<project_id>/traces/<trace_id>` diretamente. A ingestão assíncrona pode levar alguns segundos. [Modelo de dados do Langfuse](https://langfuse.com/docs/observability/data-model)

| Observação | Como interpretar |
| --- | --- |
| `query` ou `query.generate` | Duração total do pipeline, tamanho da pergunta, status HTTP final e indicação de resultado. |
| `catalog` | Dialeto e contagem de tabelas e colunas autorizadas extraídas do banco. |
| `prompt` | Tamanho da pergunta e do catálogo, quantidade de mensagens e versão das instruções. |
| `generation` | Modelo configurado, duração da chamada e validação da resposta estruturada, classificação devolvida e tokens de entrada e saída quando o provedor os informa. |
| `validation` | Tamanho do SQL candidato e aprovação pela política. Uma falha aparece como `sql_rejected`. |
| `execution` | Limite de linhas, quantidade efetivamente devolvida e indicação de truncamento. |
| `response` | Duração da montagem e codificação do JSON, tamanho em bytes e status HTTP final. |

As etapas percorridas têm duração calculada nas observações. Um erro marca a observação com status de erro e um código controlado, como `database_timeout`; as etapas puladas aparecem no histórico da resposta. O endpoint `/api/query/generate` termina após geração e montagem da resposta. Contagens de tokens ausentes ficam ausentes também na telemetria.

Entradas e saídas são registradas como resumos de campos explícitos. Credenciais, texto da pergunta, prompt, SQL, explicações, valores das linhas e mensagens brutas de exceções ficam fora dos logs e das traces. O exportador usa OTLP/HTTP, fila limitada e timeout de rede. Se o Langfuse estiver indisponível, a consulta e o SSE continuam; traces que falharem no envio são descartadas. [Mapeamento OTLP do Langfuse v4](https://langfuse.com/integrations/native/opentelemetry/migration-to-v4)

## Acompanhar uma consulta via SSE

```sh
curl --no-buffer --include http://127.0.0.1:8000/api/query/stream \
  -H 'Content-Type: application/json' \
  -H 'Accept: text/event-stream' \
  -d '{"question":"Quantos pedidos foram registrados?"}'
```

No frontend, faça um `fetch` **POST** com o JSON da pergunta e leia `response.body` como stream. Cada mensagem termina com uma linha em branco. Preserve o trecho incompleto entre leituras, pois um bloco de rede pode cortar uma mensagem ou trazer várias. Um proxy de desenvolvimento pode expor a API na mesma origem do frontend. Se houver proxy no caminho, preserve o streaming da resposta.

- `event: stage` contém `trace_id`, `name`, `status`, `duration_ms` e `error`. As fases começam com `running` e terminam com `ok` ou `failed`, à medida que são executadas.
- `event: result` contém `http_status` e `response`. Após o início do stream, a conexão tem HTTP 200 e o status da consulta vem nesse evento terminal. Erros de validação do corpo podem chegar antes da abertura do stream.
- O servidor pode enviar o comentário `: keep-alive` durante períodos sem eventos. O stream termina após o resultado e não oferece retomada ou replay.

O contrato local está em [instrumentation.py](../backend/app/instrumentation.py). Um consumidor pode implementar `EventSink` para receber transições em tempo real ou `TraceSink` para receber a trace concluída. Mantenha consumidores síncronos rápidos e envie trabalho de I/O para fora do caminho da consulta.
