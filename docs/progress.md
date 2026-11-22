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

## Avaliação Experimental de Text-to-SQL

A revisão confirmou 105 perguntas em português em 15 categorias, com referências versionadas sobre as cinco tabelas do schema `ecommerce`. A avaliação compara resultados por multiconjunto ou sequência e aplica tolerância numérica. O backend registra o resultado da validação, as latências, os tokens disponíveis e o identificador de trace. A página executa perguntas individuais ou categorias, compara modelos e exporta tentativas em CSV e JSON.

O enunciado do caso `null-06` passou a usar o limite de IDs da referência, preservando no mesmo teste clientes com e sem pedidos correspondentes. Os casos `sub-03` e `null-01` passaram a exigir, respectivamente, `IN` com subconsulta e a presença conjunta de `LEFT JOIN` e `IS NULL`. A revisão também ajustou o teste de interface para identificar o detalhe de uma tentativa pelo conceito matemático.

O PostgreSQL 18.6 temporário reproduziu o snapshot e os resultados esperados com a carga sintética de referência em 2025-01-01. Passaram os 65 testes do backend, incluindo a API local e a integração experimental com respostas simuladas, e os 6 testes do frontend. O build de produção passou com aviso de tamanho de um chunk. O backend emitiu um aviso de depreciação do cliente de teste do Starlette. A comparação com Ollama real e a entrega das traces experimentais em uma instância Langfuse ficam pendentes de uma rodada com esses serviços. [Metodologia experimental](experimental-evaluation.md)

### Avaliação dinâmica e científica

A avaliação dinâmica passou a ser o padrão. O backend valida e executa a referência e o candidato na mesma transação de leitura com isolamento `REPEATABLE READ`. Cada tentativa registra os hashes dos dados e das perguntas. A interface informa quando o resultado de referência oferece cobertura insuficiente e exibe a taxa de acerto sobre as tentativas pontuadas. O catálogo permaneceu com as mesmas 105 perguntas. A inspeção encontrou duas referências que ordenam pela data do pedido, `win-02` e `win-03`, e nenhuma com uma data literal.

O modo científico mantém o HTTP 409 quando o hash difere do manifesto e usa referências congeladas. O manifesto informa a data e a versão da seed. A avaliação registra o modelo, seu digest quando publicado pelo Ollama, a versão do prompt e as opções de geração, com semente fixa no modo científico. O seletor, a comparação, o CSV, o JSON e a telemetria incluem os metadados da tentativa.

Passaram 74 testes de backend com PostgreSQL 18.6 e API temporários, além da integração com a carga de 2026-02-01. A carga alternativa foi aceita no modo dinâmico, recebeu HTTP 409 com o manifesto científico padrão e foi aceita com um manifesto próprio. Passaram os 6 testes do frontend e o build de produção. O pytest apresentou o aviso de depreciação do cliente Starlette e o Vite avisou sobre o tamanho de um chunk. A geração foi simulada nos testes experimentais. Uma rodada com modelos reais no Ollama e entrega de traces ao Langfuse permanece pendente. [Metodologia experimental](experimental-evaluation.md)

### Automação do ambiente científico

O Makefile centraliza a reconstrução, o desenvolvimento com bind mounts, a seed protegida, a inspeção e a operação científica. A seed do Playground toma locks transacionais antes de decidir se o schema está vazio, já ocupado ou parcialmente carregado. O ambiente científico isola os volumes e as portas e seleciona o manifesto pela data. A auditoria compara o hash e os resultados das referências. O backend oferece a mesma inspeção em modo somente leitura à automação e ao proxy do frontend.

A validação com Docker Compose 2.22 reproduziu o snapshot de 2025-01-01 em execuções repetidas e confirmou as 105 perguntas, com 100 clientes, 10 categorias, 100 produtos, 1.000 pedidos e 3.000 itens. O frontend científico encaminhou a API ao dataset compatível. Uma única tentativa científica com qwen2.5:3b, caso agg-01, retornou HTTP 200 e obteve 1.000 pedidos tanto na referência quanto no SQL gerado. A tentativa ficou no CSV e no JSON com o trace local. O healthcheck do Langfuse passou. A exportação de traces ao Langfuse ficou pendente das chaves desse ambiente. A parada preservou os sete volumes científicos e os relatórios.

A reconstrução substituiu os contêineres de backend e frontend do Playground e reaproveitou o modelo. A seed encontrou as tabelas ocupadas e preservou a carga. O teste de desenvolvimento registrou um evento HMR do Vite e um reload do Uvicorn após alterações de timestamp em arquivos montados. O stack de produção voltou a responder após a parada do ambiente de desenvolvimento. O make test passou com 74 testes no backend e 6 no frontend. Os três testes condicionais foram incluídos na rodada científica, em que passaram os 14 testes do módulo experimental com geração simulada. Foram observados avisos do Starlette, do jsdom e do Vite. [Operação experimental](experimental-evaluation.md)
