#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

work_home="$(mktemp -d)"
cleanup() {
  rm -rf "${work_home}"
}
trap cleanup EXIT

cd "${root_dir}"
HOME="${work_home}" uv run python -m ytrix version
HOME="${work_home}" uv run python -m ytrix config
