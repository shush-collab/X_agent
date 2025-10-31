#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

cd "$root_dir"

echo "[infra] bringing up postgres, redis, and ollama containers..."
docker compose up -d postgres redis ollama

echo "[infra] containers requested. Use 'docker compose ps' to verify status."
