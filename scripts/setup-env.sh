#!/bin/sh
set -eu

target=$1
if [ -e "$target" ] || [ -L "$target" ]; then
    printf 'Configuração existente preservada em %s.\n' "$target"
    exit 0
fi

generate() {
    while IFS= read -r line; do
        case "$line" in
            POSTGRES_PASSWORD=|AI_QUERY_PASSWORD=|LANGFUSE_POSTGRES_PASSWORD=|LANGFUSE_REDIS_PASSWORD=|LANGFUSE_CLICKHOUSE_PASSWORD=|LANGFUSE_MINIO_PASSWORD=|LANGFUSE_NEXTAUTH_SECRET=|LANGFUSE_SALT=|LANGFUSE_ENCRYPTION_KEY=|LANGFUSE_INIT_USER_PASSWORD=)
                secret=$(openssl rand -hex 32) || return 1
                printf '%s%s\n' "$line" "$secret"
                ;;
            LANGFUSE_PUBLIC_KEY=|LANGFUSE_SECRET_KEY=)
                secret=$(openssl rand -hex 32) || return 1
                case "$line" in LANGFUSE_PUBLIC_KEY=) prefix=pk-lf- ;; *) prefix=sk-lf- ;; esac
                printf '%s%s%s\n' "$line" "$prefix" "$secret"
                ;;
            LANGFUSE_INIT_ORG_ID=) printf '%s\n' 'LANGFUSE_INIT_ORG_ID=ai-query' ;;
            LANGFUSE_INIT_USER_EMAIL=) printf '%s\n' 'LANGFUSE_INIT_USER_EMAIL=admin@ai-query.local' ;;
            VITE_LANGFUSE_PROJECT_ID=) printf '%s\n' 'VITE_LANGFUSE_PROJECT_ID=ai-query-playground' ;;
            *) printf '%s\n' "$line" ;;
        esac
    done < .env.example
}

command -v openssl >/dev/null || { printf 'Instale openssl antes de executar make setup.\n' >&2; exit 1; }
content=$(generate)
umask 077
set -C
printf '%s\n' "$content" > "$target"
printf 'Configuração local criada em %s com permissões restritas.\n' "$target"
