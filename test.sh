#!/usr/bin/env bash
set -euo pipefail

uvx ruff check .
uvx ruff format --check .
uvx mypy ytrix/

if [ -f "ytrix.py" ]; then
  uvx mypy ytrix.py
fi

uvx pytest -xvs
uvx pytest -m integration -xvs

./examples/functional_smoke.sh
