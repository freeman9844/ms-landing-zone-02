#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export AZURE_CORE_COLLECT_TELEMETRY=false
export AZURE_BICEP_CHECK_VERSION=false
for tool in python3 jq az checkov; do
  command -v "$tool" >/dev/null || { printf 'ERROR: missing validation tool: %s\n' "$tool" >&2; exit 127; }
done
python3 -m unittest discover -s tests -p 'test_*.py' -v
while IFS= read -r -d '' file; do
  bash -n "$file"
done < <(find scripts tests -type f -name '*.sh' -print0)
checkov -d infra --quiet --compact
git --no-pager diff --check
printf 'PASS: local validation only; no Azure resources were deployed.\n'
