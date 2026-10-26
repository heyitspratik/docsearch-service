#!/usr/bin/env bash
# Starts Ollama and pulls the chat model the first time. Later starts find
# the model in the volume and skip the download.
set -euo pipefail

ollama serve &
server_pid=$!

until ollama list >/dev/null 2>&1; do sleep 1; done

if ! ollama show "${OLLAMA_MODEL}" >/dev/null 2>&1; then
    echo "Pulling ${OLLAMA_MODEL} (first start only)..."
    ollama pull "${OLLAMA_MODEL}"
fi

wait "${server_pid}"
