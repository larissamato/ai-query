# AGENTS.md

## Contexto do projeto

O AI Query Playground é um projeto acadêmico de
Text-to-SQL que transforma perguntas em linguagem
natural em consultas PostgreSQL.

O objetivo é estudar e observar as etapas de
processamento de uma aplicação baseada em IA.

## Stack tecnológica

- Backend: Python e FastAPI
- Frontend: React, TypeScript, Vite e Ant Design
- Banco de dados: PostgreSQL
- Inteligência artificial: Ollama
- Validação SQL: SQLGlot
- Observabilidade: Langfuse
- Infraestrutura: Docker Compose

## Regras de desenvolvimento

- Trabalhar de maneira incremental.
- Não avançar etapas sem autorização do usuário.
- Explicar as decisões técnicas tomadas.
- Não instalar dependências desnecessárias.
- Não alterar funcionalidades fora do escopo solicitado.
- Priorizar código simples, organizado e testável.
- Não realizar commits sem autorização.

## Segurança

- Executar consultas com usuário read-only.
- Validar todo SQL gerado pela inteligência artificial.
- Nunca executar comandos destrutivos.
- Nunca expor credenciais em logs.
- Utilizar exclusivamente dados sintéticos.

## Observabilidade

- Registrar entradas e saídas do modelo.
- Registrar o SQL gerado.
- Registrar a duração de cada etapa.
- Registrar tokens quando disponíveis.
- Nunca inventar métricas ou resultados.

## Documentação

Antes de iniciar uma tarefa, consultar:

- docs/architecture.md
- docs/roadmap.md
- docs/progress.md

Ao finalizar uma tarefa:

1. Executar os testes disponíveis.
2. Atualizar o roadmap.
3. Registrar as alterações em docs/progress.md.
4. Informar arquivos criados e modificados.
5. Informar erros e pendências.
6. Aguardar autorização para a próxima etapa.

## Alterações neste arquivo

Não modificar o AGENTS.md sem autorização explícita
do usuário.
