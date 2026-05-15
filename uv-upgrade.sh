#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"

# Upgrade all dependencies
cd "$ROOT"
uv lock --upgrade
uv sync --upgrade
# to upgrade the version of python: uv venv -p 3.13.4
