#!/bin/sh
set -eu

: "${AI_QUERY_PASSWORD:?Defina AI_QUERY_PASSWORD}"
if [ "$POSTGRES_PASSWORD" = "$AI_QUERY_PASSWORD" ]; then
    printf '%s\n' 'Defina senhas distintas para o administrador e o leitor.' >&2
    exit 1
fi

psql -X --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
    --set ON_ERROR_STOP=1 --single-transaction \
    --file /opt/ai-query/sql/schema.sql \
    --file /opt/ai-query/sql/seed.sql \
    --file /opt/ai-query/sql/permissions.sql
