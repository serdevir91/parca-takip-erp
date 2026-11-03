#!/usr/bin/env bash
# One-time Codespaces setup: backend venv, frontend build, schema and demo projects.
set -euo pipefail
cd "$(dirname "$0")/.."
python -m venv backend/.venv
backend/.venv/bin/pip install --disable-pip-version-check -q -r backend/requirements.txt
(cd frontend && npm ci --no-audit --no-fund && npm run build)
mkdir -p .demo
cd backend
.venv/bin/python -m app.cli migrate
.venv/bin/python -m app.cli seed
