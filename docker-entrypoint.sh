#!/bin/sh
set -e
mkdir -p /app/data/songs /app/data/memory_workspaces
for f in intent_index.json intent_corpus.csv intent_rag_eval.json; do
  if [ ! -f "/app/data/$f" ] && [ -f "/app/seed/$f" ]; then
    cp "/app/seed/$f" "/app/data/$f"
  fi
done
exec "$@"
