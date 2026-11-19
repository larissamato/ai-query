# Progresso

## Infraestrutura inicial do PostgreSQL

O Compose provisiona o PostgreSQL 18 com volume persistente e healthcheck autenticado. O schema de e-commerce contém cinco tabelas com chaves, constraints e índices. A carga determinística cria 100 clientes, 10 categorias, 100 produtos, 1.000 pedidos e 3.000 itens. As credenciais do administrador e do leitor são configuradas por variáveis de ambiente.

A validação com Docker Compose confirmou o healthcheck, as contagens, os relacionamentos, as consultas de exemplo e a rejeição de gravação com o papel da aplicação, inclusive em uma transação explicitamente aberta para escrita. Dois volumes novos produziram dumps de dados idênticos com a data de referência fixa. O dump também permaneceu idêntico após recriar o contêiner com o mesmo volume. Uma terceira inicialização confirmou a janela padrão dos últimos 12 meses completos e a restrição de acesso do leitor aos bancos auxiliares.

Os comandos de reprodução estão no [README](../README.md). Ollama e o catálogo para o pipeline continuam pendentes de autorização.

## API inicial e catálogo PostgreSQL

O backend FastAPI usa Pydantic para configuração e contratos HTTP, e psycopg para conexão com o papel fixo `ai_query_reader`. A conexão usa transação somente leitura e timeout. O catálogo cruza a lista de tabelas permitidas com os privilégios efetivos de leitura e retorna metadados estruturados e um contexto textual compacto.

A suíte passou com 11 testes, incluindo integração dos endpoints com PostgreSQL 18 no Compose. O teste de integração conferiu as cinco tabelas, a chave primária composta, o tipo numérico com precisão e escala, as quatro relações e a disponibilidade da documentação Swagger. Com o PostgreSQL parado, os dois endpoints retornaram HTTP 503. Após religar o banco, o healthcheck voltou a responder com HTTP 200.

O [README](../README.md) documenta os testes via Swagger, curl e pytest. A integração do modelo continua pendente de autorização.

## Geração de SQL com Ollama

A API ganhou `POST /api/query/generate`. O serviço Text-to-SQL combina instruções versionadas, catálogo autorizado e pergunta, e usa a interface `LLMProvider`. O adaptador Ollama solicita a saída estruturada pelo JSON Schema. O contrato diferencia uma consulta candidata, uma pergunta ambígua e uma pergunta sem resposta no catálogo. O SQL candidato é devolvido sem execução.

O perfil `llm` adiciona o Ollama ao Compose e mantém o modelo em volume. O modelo padrão é `qwen2.5:3b`, escolhido após medir os recursos e comparar dois modelos em CPU. Cada chamada ao provedor registra versão, modelo, latência e tokens disponíveis. A captura de mensagens e resposta é configurável para sessões sintéticas.

A suíte passou com 22 testes quando executada com a API e o PostgreSQL reais no Compose. Os testes da geração usam um Ollama simulado para verificar o contrato, estados sem SQL, erros e logs sem depender do comportamento do modelo. Os comandos e exemplos em português estão no [README](../README.md).

No Ollama real, o modelo de 3B gerou uma contagem correta de pedidos e identificou que o catálogo não contém CPF. Para “Quais foram os melhores pedidos?”, ele escolheu uma métrica sem confirmação. O modelo de 1,5B acertou a contagem, mas errou as duas classificações. Os testes simulados verificam que a API representa a ambiguidade com SQL nulo quando o modelo a sinaliza. A captura de prompt e resposta também foi conferida no Compose com a configuração ativada.

### Revisão da etapa de geração

Na revisão, `pytest backend` passou com 21 testes e pulou o teste de integração condicionado a `AI_QUERY_TEST_BASE_URL`. A suíte simulada confirmou o contrato HTTP, a troca de provedor e a ausência de execução do SQL candidato. O contrato valida a forma da resposta, mas aceita `generated` para uma pergunta ambígua caso o modelo escolha uma métrica. Em falhas do provedor, o identificador da geração fica no log e não aparece na resposta HTTP. Com a captura de conteúdo ativa, respostas com envelope inválido do Ollama são registradas com `response: null`.

A consulta de estado do Compose parou na configuração por falta de `POSTGRES_PASSWORD`. Nesta revisão, o ensaio com serviços reais não foi repetido e nenhum SQL gerado foi executado.

## Validação e execução limitada de SQL

`POST /api/query` aceita uma pergunta e retorna o estado e a duração de catálogo, geração, validação e execução. O serviço usa SQLGlot 29.0.1 para analisar uma única instrução PostgreSQL, aplicar listas explícitas de nós, funções e tipos, e resolver referências a CTEs por escopo. As tabelas físicas precisam pertencer ao catálogo visível da requisição. O executor usa o SQL renderizado da AST aprovada e reutiliza a conexão do leitor com transação somente leitura e timeout de 3 segundos. A consulta lê até 101 linhas para devolver no máximo 100 com indicação de truncamento.

A suíte passou com 53 testes, incluindo PostgreSQL 18.6 temporário com a carga sintética, teste HTTP da API e casos de sucesso, resultado vazio, truncamento e bloqueio de prompt injection. A integração da execução usou um provedor simulado. O teste de erro HTTP 504 simulou o cancelamento, enquanto a integração verificou o `statement_timeout` e o papel read-only no PostgreSQL real. A qualidade da geração com Ollama real não foi reavaliada nesta etapa.

## Observabilidade local e SSE

O Compose complementar usa Langfuse 4.78.0 com web, worker, PostgreSQL dedicado, ClickHouse, Redis e MinIO. O backend instrumenta catálogo, prompt, geração, validação, execução e resposta sob o mesmo `trace_id`. A instrumentação tem consumidores próprios para eventos imediatos e traces concluídas. O SSE transmite mudanças de estado sem depender do Langfuse. O exportador OTLP/HTTP envia a trace concluída em segundo plano. A opção anterior de log bruto foi retirada. Os registros de entrada e saída usam resumos, contagens e códigos controlados.

A suíte passou com 57 testes, incluindo PostgreSQL 18.6 temporário, isolamento de falha do consumidor de telemetria e entrega do evento SSE antes da resposta do provedor. Um Langfuse temporário em Docker recebeu sete observações de uma consulta aprovada e seis de uma rejeitada, com verificação do modelo, dos tokens e do erro de validação pela API de observações v2. O canário usou geração simulada. O [guia de observabilidade](observability.md) documenta a inicialização, o acesso à interface e o contrato SSE.

## Frontend do AI Query Playground

A aplicação local usa React, Vite, TypeScript estrito e Ant Design. Os componentes exibem o catálogo, os modelos instalados, o progresso SSE, o prompt original, o SQL PostgreSQL destacado em modo somente leitura, a validação, os resultados e as métricas. O histórico armazena até 20 perguntas e seus metadados no navegador. O gráfico requer um resultado completo com duas colunas e pares de categoria e valor numérico. A configuração pública do projeto habilita links para as traces atuais e históricas.

O backend acrescentou `GET /api/models` e os campos opcionais `model` e `include_prompt` às requisições de execução. O modelo escolhido é conferido contra o catálogo local do Ollama. As mensagens exatas retornam apenas à requisição que solicitou a visualização, com cache desabilitado. A telemetria continua registrando resumos.

O build do Vite com verificação TypeScript passou, assim como 5 testes do frontend e 58 do backend. No Chrome, o build final carregou os modelos do Ollama e o schema real. A pergunta de contagem gerou SQL com `qwen2.5:3b`, a validação aprovou a consulta e a tabela exibiu os 1.000 pedidos da base sintética PostgreSQL. O teste conferiu as abas de SQL e de prompt, a inclusão no histórico, o ID da trace e o layout a 390 px. A construção do link do Langfuse foi testada com um ID de projeto configurado para o teste. As instruções de execução estão no [README](../README.md#frontend-do-playground).

## Operação completa com Docker Compose

O Makefile reúne `setup`, `up`, `down`, `restart`, `build`, `logs`, `status`, `test`, `benchmark` e `help`. O setup prepara segredos em arquivo novo com permissão `0600`, constrói as imagens e baixa o modelo. O Compose espera o banco de estudo e o modelo antes de iniciar o backend, e espera o backend antes de iniciar o frontend. Nginx serve o build e encaminha a API e o SSE. O Langfuse inicializa usuário, organização, projeto e chaves quando recebe a configuração gerada em um ambiente novo. O comando `down` usa `stop` para preservar contêineres e volumes.

O benchmark executa cinco perguntas versionadas pelo endpoint real, com referências consultadas na base sintética usando o leitor. A saída JSON distingue equivalência de resultados, erros de classificação, rejeições e falhas operacionais e registra latências, tokens e traces. Na rodada de verificação com `qwen2.5:3b`, os cinco casos corresponderam às referências.

Os dez comandos foram executados em um projeto Compose isolado no Arch Linux. O `setup` baixou o modelo em um volume novo e preservou o arquivo de configuração no segundo uso. `make test` passou com 60 testes do backend e 5 do frontend. A subida e o reinício deixaram saudáveis os dez serviços de execução e o inicializador terminou com código zero. A parada preservou os sete volumes e os hashes dos arquivos de configuração local e de teste. O [README](../README.md) contém os passos de instalação e operação.

Após a parada, `make status` sinalizou indisponibilidade. Na nova subida, o proxy Nginx entregou o SSE e a consulta retornou os 1.000 pedidos preservados. As chaves geradas no setup autenticaram na API do Langfuse, que retornou as sete observações da consulta. O jsdom emitiu avisos de CSS durante o teste do frontend, que passou.
