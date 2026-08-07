#!/usr/bin/env bash
# Run the first model campaign as two stages: 2 fresh sessions, then 16.

set -Eeuo pipefail

readonly MAX_BATCH_SECONDS=43200
readonly STAGES=(2 16)

DOCKER_CONTEXT="${DOCKER_CONTEXT:-default}"
API_KEY_FILE=""
BATCH_ROOT="${BATCH_ROOT:-}"

usage() {
  cat <<'EOF'
Usage: bash tools/run_model_gateway_batch.sh --api-key-file PATH [options]

Runs qwen3.8-max through native OpenCode 1.18.14 with temperature=0.6 and
thinking=disabled. Stage 1 creates 2 fresh sessions; stage 2 creates 16 fresh
sessions. The whole 18-run batch has one 12-hour hard limit.

Options:
  --api-key-file PATH   Required Token Plan key file
  --context NAME        Docker context (default: default)
  --batch-root PATH     Evidence root for all 18 repeats
  -h, --help            Show this help
EOF
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --api-key-file)
      [[ $# -ge 2 ]] || die "--api-key-file requires a path"
      API_KEY_FILE="$2"
      shift 2
      ;;
    --context)
      [[ $# -ge 2 ]] || die "--context requires a value"
      DOCKER_CONTEXT="$2"
      shift 2
      ;;
    --batch-root)
      [[ $# -ge 2 ]] || die "--batch-root requires a path"
      BATCH_ROOT="$2"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      die "unknown argument: $1"
      ;;
  esac
done

[[ -n "$API_KEY_FILE" ]] || die "--api-key-file is required"
[[ -f "$API_KEY_FILE" && ! -L "$API_KEY_FILE" && -s "$API_KEY_FILE" ]] || \
  die "API key must be a non-empty, non-symlink regular file"
command -v timeout >/dev/null 2>&1 || die "timeout is required"
command -v sha256sum >/dev/null 2>&1 || die "sha256sum is required"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
if [[ -z "$BATCH_ROOT" ]]; then
  BATCH_ROOT="${HOME}/evaluation-test-evidence/model-batch-${STAMP}"
fi
mkdir -p "$BATCH_ROOT"
BATCH_ROOT="$(cd -- "$BATCH_ROOT" && pwd -P)"

started="$(date +%s)"
build_flag=()
completed=0

for stage_size in "${STAGES[@]}"; do
  stage_dir="$BATCH_ROOT/stage-${stage_size}"
  mkdir -p "$stage_dir"
  for ((repeat=1; repeat<=stage_size; repeat++)); do
    now="$(date +%s)"
    elapsed=$((now - started))
    remaining=$((MAX_BATCH_SECONDS - elapsed))
    (( remaining > 0 )) || die "12-hour batch deadline exhausted before repeat $repeat/$stage_size"
    run_dir="$stage_dir/repeat-$(printf '%02d' "$repeat")"
    printf 'stage=%d repeat=%d/%d remaining_seconds=%d\n' \
      "$stage_size" "$repeat" "$stage_size" "$remaining"
    timeout --signal=TERM --kill-after=30s "${remaining}s" \
      bash "$SCRIPT_DIR/run_model_gateway_validation.sh" \
        --context "$DOCKER_CONTEXT" \
        --evidence-dir "$run_dir" \
        --invoke-primary \
        --api-key-file "$API_KEY_FILE" \
        "${build_flag[@]}"
    build_flag=(--skip-build)
    completed=$((completed + 1))
  done
done

finished="$(date +%s)"
cat >"$BATCH_ROOT/batch-summary.txt" <<EOF
timestamp_utc=$STAMP
opencode_version=1.18.14
protocol=anthropic_compatible_messages
model=qwen3.8-max
temperature=0.6
thinking=disabled
stages=2,16
fresh_sessions=18
completed=$completed
elapsed_seconds=$((finished - started))
max_batch_seconds=$MAX_BATCH_SECONDS
status=PASS
EOF

(
  cd "$BATCH_ROOT"
  find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
  sha256sum -c SHA256SUMS
)

printf '\nPASS: first-round OpenCode batch (2 + 16 fresh sessions)\n'
printf 'Evidence: %s\n' "$BATCH_ROOT"
