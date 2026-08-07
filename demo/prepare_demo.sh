#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: bash demo/prepare_demo.sh [OUTPUT_DIR]

Prepare and validate the fixed real-source production demo.
OUTPUT_DIR defaults to /tmp/global-geochemical-atlas-live and must be new or empty.
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "${script_dir}/.." && pwd)"
output_dir="${1:-/tmp/global-geochemical-atlas-live}"

if [[ -e "${output_dir}" ]] && find "${output_dir}" -mindepth 1 -print -quit 2>/dev/null | grep -q .; then
  printf 'Refusing to overwrite non-empty output directory: %s\n' "${output_dir}" >&2
  printf 'Choose a new path, for example: %s\n' "/tmp/global-geochemical-atlas-live-2" >&2
  exit 64
fi

mkdir -p "${output_dir}"

python3 "${repo_root}/skills/global-geochemical-atlas/scripts/run_atlas_request.py" \
  --request "${repo_root}/skills/global-geochemical-atlas/fixtures/production-usgs/request.json" \
  --demo production-usgs \
  --analysis-profile production \
  --generated-at 2026-08-07T00:00:00Z \
  --output-dir "${output_dir}"

python3 "${repo_root}/skills/global-geochemical-atlas/scripts/validate_outputs.py" \
  --output-dir "${output_dir}"

printf '\nDemo prepared and validated.\n'
printf 'Interactive map: %s/interactive_map.html\n' "${output_dir}"
printf 'Run summary:     %s/run_summary.json\n' "${output_dir}"
printf 'Source manifest: %s/source_manifest.json\n' "${output_dir}"
printf 'QC report:       %s/qc_report.json\n' "${output_dir}"
printf 'Anomaly report:  %s/anomaly_report.json\n' "${output_dir}"
