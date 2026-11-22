# Avaliação Experimental de Text-to-SQL

A suíte contém 105 perguntas em português, sete por categoria. O catálogo versionado define a pergunta, o conceito matemático, a complexidade, a classificação esperada e, quando aplicável, o SQL e a construção exigida. A complexidade é uma classificação qualitativa por grupo. Os resultados esperados ficam em um arquivo separado, produzido pelo PostgreSQL a partir das consultas escritas e revisadas sem participação do modelo. [Catálogo de casos](../backend/evaluation/experimental_cases.json) · [Resultados de referência](../backend/evaluation/experimental_snapshot.json)

## Schema e snapshot

O schema `ecommerce` contém `customers`, `categories`, `products`, `orders` e `order_items`. As quatro chaves estrangeiras ligam produto a categoria, pedido a cliente e item a pedido e a produto. O item tem chave primária composta por pedido e produto. As colunas físicas são obrigatórias, inclusive as colunas da chave composta. Os casos de lógica ternária usam nulos introduzidos por junções externas, expressões e agregados sobre conjuntos vazios. Os casos de junção externa filtram os lados para que haja linhas sem correspondência, apesar da integridade referencial. [DDL PostgreSQL](../infra/postgres/sql/schema.sql)

## Modos de avaliação

**Dinâmica — banco atual** é o modo padrão. O backend calcula o SHA-256 das linhas visíveis, ordenadas por chave primária, e executa o SQL de referência validado e o SQL do modelo na mesma transação `REPEATABLE READ`, com o papel `ai_query_reader`. Cada tentativa identifica a carga pelo hash dos dados (`snapshot_sha256`) e a versão das perguntas pelo hash do catálogo (`dataset_sha256`). Tentativas sucessivas podem observar cargas diferentes se houver alterações entre elas.

Nenhuma das 105 perguntas contém uma data fixa. `win-02` e `win-03` usam `ordered_on` para calcular `RANK` e `DENSE_RANK`. A seed posiciona os pedidos nos 12 meses completos anteriores a `SEED_REFERENCE_DATE`, que por padrão é o primeiro dia do mês corrente em UTC na inicialização.

A referência dinâmica sinaliza dados insuficientes quando não há linhas, quando todas as células são nulas ou quando o resultado da referência excede o limite de 100 linhas. `quant-06` e `null-05` exercitam explicitamente conjuntos vazios e aceitam, respectivamente, zero linhas e a média nula. Uma contagem zero é um resultado comparável. A sinalização é uma heurística de cobertura. Conjuntos com poucas linhas ou com baixa variedade também podem fazer consultas diferentes coincidirem. Rejeições de SQL, divergências de classificação e falhas operacionais conservam sua classificação.

**Científica — snapshot controlado** usa o manifesto versionado de referência. O manifesto padrão registra a seed `ecommerce-v1` com data `2025-01-01`. Antes de chamar o modelo, o backend compara o hash dos dados atuais com o manifesto e responde HTTP 409 em caso de divergência. O manifesto associa o hash das perguntas, o hash dos dados, a data, a versão da seed e os resultados congelados. A verificação, o catálogo e a execução do candidato compartilham a mesma transação somente leitura. Cada tentativa registra também o modelo solicitado e retornado, o digest fornecido pelo Ollama quando disponível, a versão do prompt e a configuração enviada ao gerador, incluindo a semente 42 da geração no modo científico. Registre a versão do Ollama e o ambiente de execução para repetir a rodada.

## Operação pelo Makefile

A partir da raiz do repositório, execute:

```sh
make seed-benchmark
make snapshot
make experiment-up
make models
make benchmark BENCHMARK_CASE=agg-01 BENCHMARK_REPEATS=1
```

`experiment-up` já executa `seed-benchmark`. A carga usa a seed existente com `REFERENCE_DATE=2025-01-01`. O projeto `ai-query-experimental-2025-01-01` possui rede, volumes e nomes próprios. O comando audita o hash e os resultados congelados antes de subir o frontend. Em seguida, verifica o dataset pela API encaminhada pelo frontend, a lista de modelos e a autenticação do projeto Langfuse quando configurada. Use a seção **Ollama científico** de `make models` para selecionar tags da rodada. Na primeira subida, o inicializador pode baixar o modelo padrão se estiver ausente no Ollama isolado. `make benchmark` e `make benchmark-all` usam o stack já iniciado e consultam apenas os modelos instalados.

| Serviço científico | Endereço padrão | Variável do Makefile |
| --- | --- | --- |
| Frontend | http://127.0.0.1:5174 | `EXPERIMENT_FRONTEND_PORT` |
| API | http://127.0.0.1:8001 | `EXPERIMENT_API_PORT` |
| Langfuse | http://localhost:3001 | `EXPERIMENT_LANGFUSE_PORT` |
| MinIO | http://localhost:9091 | `EXPERIMENT_MINIO_PORT` |

Passe portas diferentes se outro projeto já as usar. Abra o frontend científico e selecione **Avaliação Experimental**, **Científica — snapshot controlado**, a pergunta ou categoria e os modelos. As tentativas no navegador ficam disponíveis na sessão da página. Exporte CSV ou JSON para guardá-las.

No terminal, use `BENCHMARK_CASE=agg-01` ou `BENCHMARK_CATEGORY="Funções de agregação"`. Sem filtro, o benchmark executa `agg-01`. `make benchmark-all` percorre as 105 perguntas sequencialmente por modelo. Por padrão, inclui as tags que o Ollama anuncia com capacidade de geração de texto local. Use `BENCHMARK_MODELS="tag-a tag-b"` para indicar os modelos configurados para a rodada. Em versões do Ollama que omitem capacidades, a seleção usa o modelo padrão ou as tags indicadas. A capacidade anunciada é um filtro de disponibilidade. A suíte mede o desempenho em Text-to-SQL. [Capacidades por modelo do Ollama](https://docs.ollama.com/api-reference/show-model-details)

Os relatórios ficam em pastas exclusivas dentro de `BENCHMARK_OUTPUT` (padrão `artifacts/benchmarks`), com `results.json` e `attempts.csv`. O JSON inclui o dataset, as métricas consolidadas e por modelo e as tentativas com hashes, SQL, resultados, estágios e IDs de trace. O terminal indica o progresso e diferencia falhas de infraestrutura, geração, validação, execução e equivalência. Divergências científicas integram a pontuação. O runner retorna erro de processo se houver falha operacional e preserva o relatório produzido até a interrupção.

`make experiment-down` para os serviços e preserva volumes e relatórios. Se `make snapshot` indicar incompatibilidade em um volume existente, preserve-o e prepare outro projeto da mesma data com `make seed-benchmark EXPERIMENT_SUFFIX=reproducao`. Passe `EXPERIMENT_SUFFIX=reproducao` nos demais comandos dessa rodada e use portas livres. A troca de `REFERENCE_DATE` seleciona outro projeto e exige um manifesto revisado em `backend/evaluation/experimental_snapshot-AAAA-MM-01.json`.

### Versionar uma nova data

Em um projeto Compose inédito, inicialize apenas o PostgreSQL com a nova data e capture a referência.

```sh
reference=2026-02-01
export SEED_REFERENCE_DATE="$reference"
docker compose --env-file .env -p "ai-query-manifesto-$reference" up --wait postgres
docker compose --env-file .env -p "ai-query-manifesto-$reference" run --build --rm --no-deps -T backend \
  python -m evaluation.freeze_snapshot --reference-date "$reference" --seed-version ecommerce-v1 \
  > "/tmp/experimental_snapshot-$reference.json"
docker compose --env-file .env -p "ai-query-manifesto-$reference" stop
```

Revise e versione o manifesto em `backend/evaluation/experimental_snapshot-AAAA-MM-01.json`. Rode `make seed-benchmark REFERENCE_DATE=AAAA-MM-01` para verificar a reprodução em outro volume. Use a mesma data nos demais comandos científicos. Na instalação com o executável independente, use `docker-compose`.

A auditoria de `seed-benchmark` usa `evaluation.freeze_snapshot`. Ela executa cada referência diretamente e depois da validação, confere o limite de linhas e a construção solicitada e compara a captura com o manifesto. `snapshot` confere o hash em uma transação somente leitura e mostra as contagens do mesmo snapshot.

Com as dependências de desenvolvimento do backend instaladas e a conexão apontada para esse snapshot, execute `AI_QUERY_TEST_EXPERIMENTAL=1 python -m pytest backend/tests/test_experimental.py` na raiz. A integração compara as referências reproduzidas com o arquivo versionado e verifica a classificação da API com respostas simuladas. Em uma instância sintética inicializada com outra data, use `AI_QUERY_TEST_ALTERNATE_REFERENCE_DATE=AAAA-MM-01 python -m pytest backend/tests/test_experimental.py -k dynamic_endpoint_on_postgresql` para verificar a aceitação em modo dinâmico, o HTTP 409 com o manifesto padrão e a aceitação científica com um manifesto compatível.

## Critérios de avaliação

- Compare a aridade mesmo quando o resultado estiver vazio. Respeite a posição das colunas e compare os nomes quando forem pedidos explicitamente.
- Compare linhas como multiconjunto, preservando multiplicidades. Quando a pergunta exigir ordem, compare a sequência e verifique o `ORDER BY` externo. Resultados truncados falham, inclusive quando o prefixo coincide.
- Compare números nativos usando erro absoluto de até `10⁻⁶` ou erro relativo de até `10⁻⁹` em relação à maior magnitude. O pareamento de linhas é um a um. Texto, booleanos e nulos mantêm seus tipos.
- Casos com construção explícita exigem equivalência do resultado e uma verificação sintática da AST PostgreSQL. Exemplos incluem os lados da junção, `UNION` com e sem `ALL`, quantificadores e correlação por escopo. A verificação estrutural registra a presença da construção. Ela tem limites para provar que um operador produziu determinado valor.
- Para perguntas ambíguas ou sem dados no catálogo, compare a classificação esperada e exija SQL ausente, conforme o contrato do gerador. Os casos de segurança incluem instruções simuladas que tentam mudar a classificação e o resultado. Rejeições da política são registradas separadamente. A validação do candidato continua obrigatória antes da execução.
- A política experimental admite `UNION`, `INTERSECT`, `EXCEPT`, `ANY` e `ALL` sob as mesmas restrições de catálogo e de leitura. O executor mantém o timeout de três segundos e a devolução de até 100 linhas com sinalização de truncamento.

Cada tentativa inclui SQL de referência e do modelo, resultados, estágios, latências, tokens quando disponíveis, classificação, versão do prompt e ID de trace. Os textos e resultados são exibidos na resposta da avaliação. O exportador Langfuse recebe os resumos do pipeline conforme a configuração existente. O ID é atribuído localmente e o envio ao Langfuse é em melhor esforço.

## Interpretação

A tabela agrupa os resultados por modelo e hash dos dados no modo selecionado. A taxa de acerto divide as tentativas corretas pelo total de tentativas pontuadas. Dados insuficientes aparecem em uma coluna própria e ficam fora do denominador. As demais são classificadas por resultado, construção, classificação, política ou falha operacional. Falhas que impedem a tentativa, como divergência do snapshot ou desconexão do navegador, interrompem a rodada e são exibidas na interface. A latência total do backend inclui verificação do snapshot, seleção do modelo, pipeline e classificação. Tempos de geração e execução ficam disponíveis individualmente, e estágios não percorridos têm duração ausente.

Compare modelos no mesmo conjunto de perguntas e com o mesmo número de repetições. Exporte cada rodada e registre o ambiente, as tags e versões dos modelos e a ordem de execução. Carregamento inicial do modelo e alternância entre modelos podem afetar as latências. A precisão desta suíte descreve o desempenho no snapshot, cujas regularidades podem fazer consultas semanticamente diferentes coincidirem. Os testes de referência e as simulações da API verificam a infraestrutura de avaliação. Métricas de modelos exigem execuções reais.
