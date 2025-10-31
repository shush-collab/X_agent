#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$root_dir"

echo "[infra] stopping postgres, redis, and ollama containers..."
docker compose stop postgres redis ollama
