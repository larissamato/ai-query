#!/bin/sh
set -eu
"$@" ps --all --format 'table {{.Service}}\t{{.Status}}'
services=$("$@" config --services)
failed=0
for service in $services; do
    container=$("$@" ps --all --quiet "$service")
    if [ -n "$container" ]; then
        state=$(docker inspect --format '{{if and (eq .State.Status "running") .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}:{{.State.ExitCode}}{{end}}' "$container")
    else
        state=ausente
    fi
    case "$service:$state" in
        ollama-model:exited:0|*:healthy) ;;
        *)
            printf '%s: %s\n' "$service" "$state" >&2
            failed=1
            ;;
    esac
done
exit "$failed"
