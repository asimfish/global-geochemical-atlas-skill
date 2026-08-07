#!/usr/bin/env bash
# Run the public evaluation validator in the review-compliant Docker sandbox.

set -Eeuo pipefail

readonly CPU_LIMIT="2"
readonly MEMORY_LIMIT="4g"
readonly MEMORY_SWAP_LIMIT="4g"
readonly PIDS_LIMIT="256"
readonly TASK_TIMEOUT_SECONDS="43200"
readonly HOST_TIMEOUT_SECONDS="43230"
readonly EXPECTED_PUBLIC_TASKS="8"

DOCKER_CONTEXT="${DOCKER_CONTEXT:-default}"
TRANSFER_CONTEXT="${TRANSFER_CONTEXT:-rootless}"
TEST_IMAGE="${TEST_IMAGE:-python:3.12-slim}"
EVIDENCE_DIR="${EVIDENCE_DIR:-}"

usage() {
  cat <<'EOF'
Usage: bash tools/run_docker_validation.sh [options]

Run evaluation Public Q01-Q08 with the fixed review profile:
  2 CPU, 4 GiB memory, no extra swap, no GPU, no network,
  read-only root filesystem, 256 PIDs, and a 12-hour (43200-second) timeout.

Options:
  --context NAME       Docker context used for the test (default: default)
  --transfer-context N Context used as an offline image source (default: rootless)
  --image IMAGE        Python test image (default: python:3.12-slim)
  --evidence-dir PATH  Evidence output directory
  -h, --help           Show this help

Environment variables with the same names are also supported:
  DOCKER_CONTEXT, TRANSFER_CONTEXT, TEST_IMAGE, EVIDENCE_DIR

CPU, memory, GPU, network, PID, and timeout limits are intentionally not
configurable. Changing them would no longer reproduce the review profile.
EOF
}

die() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

require_command() {
  command -v "$1" >/dev/null 2>&1 || die "required command not found: $1"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --context)
      [[ $# -ge 2 ]] || die "--context requires a value"
      DOCKER_CONTEXT="$2"
      shift 2
      ;;
    --transfer-context)
      [[ $# -ge 2 ]] || die "--transfer-context requires a value"
      TRANSFER_CONTEXT="$2"
      shift 2
      ;;
    --image)
      [[ $# -ge 2 ]] || die "--image requires a value"
      TEST_IMAGE="$2"
      shift 2
      ;;
    --evidence-dir)
      [[ $# -ge 2 ]] || die "--evidence-dir requires a value"
      EVIDENCE_DIR="$2"
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

require_command docker
require_command python3
require_command sha256sum
require_command timeout
require_command find
require_command sort
require_command xargs

[[ "$(uname -s)" == "Linux" ]] || die "this runner requires Linux"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
EVALUATION_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
REPOSITORY_DIR="$(cd -- "$EVALUATION_DIR/.." && pwd -P)"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"

if [[ -z "$EVIDENCE_DIR" ]]; then
  EVIDENCE_DIR="${HOME}/evaluation-test-evidence/${STAMP}"
fi
mkdir -p "$EVIDENCE_DIR"
EVIDENCE_DIR="$(cd -- "$EVIDENCE_DIR" && pwd -P)"

case "$EVIDENCE_DIR/" in
  "$EVALUATION_DIR/"*)
    die "evidence directory must be outside the read-only evaluation tree"
    ;;
esac

CONTAINER_NAME="gga-evaluation-${STAMP,,}"
CONTAINER_CREATED=0

cleanup() {
  local status=$?
  trap - EXIT INT TERM
  if [[ "$CONTAINER_CREATED" -eq 1 ]]; then
    docker --context "$DOCKER_CONTEXT" rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
  fi
  exit "$status"
}
trap cleanup EXIT INT TERM

printf 'Repository: %s\n' "$REPOSITORY_DIR"
printf 'Evaluation: %s\n' "$EVALUATION_DIR"
printf 'Docker context: %s\n' "$DOCKER_CONTEXT"
printf 'Evidence: %s\n' "$EVIDENCE_DIR"

docker context ls >"$EVIDENCE_DIR/docker-contexts.txt"
docker --context "$DOCKER_CONTEXT" version >"$EVIDENCE_DIR/docker-version.txt"
docker --context "$DOCKER_CONTEXT" info >"$EVIDENCE_DIR/docker-info.txt"

CGROUP_VERSION="$(docker --context "$DOCKER_CONTEXT" info --format '{{.CgroupVersion}}')"
[[ "$CGROUP_VERSION" == "2" ]] || die "Docker context $DOCKER_CONTEXT must use cgroup v2"

if ! docker --context "$DOCKER_CONTEXT" image inspect "$TEST_IMAGE" >/dev/null 2>&1; then
  if [[ "$TRANSFER_CONTEXT" != "$DOCKER_CONTEXT" ]] && \
     docker --context "$TRANSFER_CONTEXT" image inspect "$TEST_IMAGE" >/dev/null 2>&1; then
    printf 'Loading %s from Docker context %s...\n' "$TEST_IMAGE" "$TRANSFER_CONTEXT"
    docker --context "$TRANSFER_CONTEXT" save "$TEST_IMAGE" | \
      docker --context "$DOCKER_CONTEXT" load \
      >"$EVIDENCE_DIR/image-offline-load.log"
  else
    printf 'Pulling %s with Docker context %s...\n' "$TEST_IMAGE" "$DOCKER_CONTEXT"
    docker --context "$DOCKER_CONTEXT" pull "$TEST_IMAGE" \
      >"$EVIDENCE_DIR/image-pull.log" 2>&1 || \
      die "image pull failed; see $EVIDENCE_DIR/image-pull.log"
  fi
fi

docker --context "$DOCKER_CONTEXT" image inspect "$TEST_IMAGE" \
  >"$EVIDENCE_DIR/image-inspect.json"
IMAGE_ID="$(docker --context "$DOCKER_CONTEXT" image inspect --format '{{.Id}}' "$TEST_IMAGE")"

set +e
docker --context "$DOCKER_CONTEXT" create \
  --name "$CONTAINER_NAME" \
  --cpus "$CPU_LIMIT" \
  --memory "$MEMORY_LIMIT" \
  --memory-swap "$MEMORY_SWAP_LIMIT" \
  --pids-limit "$PIDS_LIMIT" \
  --read-only \
  --tmpfs /tmp:rw,nosuid,nodev,noexec,size=1g,mode=1777 \
  --network none \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --user "$(id -u):$(id -g)" \
  --env HOME=/tmp/home \
  --env TMPDIR=/tmp \
  --env PYTHONDONTWRITEBYTECODE=1 \
  --env CUDA_VISIBLE_DEVICES= \
  --env NVIDIA_VISIBLE_DEVICES=void \
  --mount "type=bind,src=$EVALUATION_DIR,dst=/work/evaluation,readonly" \
  --mount "type=bind,src=$EVIDENCE_DIR,dst=/evidence" \
  --workdir /work/evaluation \
  "$TEST_IMAGE" \
  sh -lc '
    set -eu
    mkdir -p "$HOME"
    {
      echo "cpu.max=$(cat /sys/fs/cgroup/cpu.max 2>/dev/null || echo unavailable)"
      echo "memory.max=$(cat /sys/fs/cgroup/memory.max 2>/dev/null || echo unavailable)"
      echo "memory.swap.max=$(cat /sys/fs/cgroup/memory.swap.max 2>/dev/null || echo unavailable)"
      echo "pids.max=$(cat /sys/fs/cgroup/pids.max 2>/dev/null || echo unavailable)"
      echo "CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES-<unset>}"
      echo "NVIDIA_VISIBLE_DEVICES=${NVIDIA_VISIBLE_DEVICES-<unset>}"
      if find /dev -maxdepth 1 -name "nvidia*" -print -quit | grep -q .; then
        echo "gpu_devices=present"
        find /dev -maxdepth 1 -name "nvidia*" -print
      else
        echo "gpu_devices=none"
      fi
    } > /evidence/runtime-limits.txt
    timeout --signal=TERM --kill-after=5s 43200s \
      python3 tools/validate_package.py . --public-only \
      --report /evidence/package-validation.json
  ' >"$EVIDENCE_DIR/container-create.out" 2>"$EVIDENCE_DIR/container-create.err"
CREATE_STATUS=$?
set -e

[[ "$CREATE_STATUS" -eq 0 ]] || {
  cat "$EVIDENCE_DIR/container-create.err" >&2
  die "Docker could not create the review-compliant container"
}
CONTAINER_CREATED=1

docker --context "$DOCKER_CONTEXT" inspect "$CONTAINER_NAME" \
  >"$EVIDENCE_DIR/container-inspect-pre.json"

python3 - \
  "$EVIDENCE_DIR/container-inspect-pre.json" \
  "$EVALUATION_DIR" \
  "$EVIDENCE_DIR" \
  "$(id -u):$(id -g)" <<'PY' \
  | tee "$EVIDENCE_DIR/resource-contract.txt"
import json
import sys
from pathlib import Path

inspect_path, evaluation_dir, evidence_dir, expected_user = sys.argv[1:]
container = json.loads(Path(inspect_path).read_text(encoding="utf-8"))[0]
host = container["HostConfig"]
config = container["Config"]

expected = {
    "NanoCpus": 2_000_000_000,
    "Memory": 4_294_967_296,
    "MemorySwap": 4_294_967_296,
    "PidsLimit": 256,
    "NetworkMode": "none",
    "ReadonlyRootfs": True,
}
for key, value in expected.items():
    actual = host.get(key)
    if actual != value:
        raise SystemExit(f"resource contract mismatch: {key}={actual!r}, expected {value!r}")

if host.get("DeviceRequests") not in (None, []):
    raise SystemExit(f"GPU device request is forbidden: {host['DeviceRequests']!r}")
if "ALL" not in (host.get("CapDrop") or []):
    raise SystemExit("CapDrop must contain ALL")
if "no-new-privileges" not in (host.get("SecurityOpt") or []):
    raise SystemExit("no-new-privileges is missing")
if config.get("User") != expected_user:
    raise SystemExit(f"container user mismatch: {config.get('User')!r}")
if config.get("WorkingDir") != "/work/evaluation":
    raise SystemExit(f"working directory mismatch: {config.get('WorkingDir')!r}")

env = dict(item.split("=", 1) for item in config.get("Env", []) if "=" in item)
if env.get("CUDA_VISIBLE_DEVICES") != "":
    raise SystemExit("CUDA_VISIBLE_DEVICES must be empty")
if env.get("NVIDIA_VISIBLE_DEVICES") != "void":
    raise SystemExit("NVIDIA_VISIBLE_DEVICES must be void")

mounts = {item["Destination"]: item for item in container.get("Mounts", [])}
if set(mounts) != {"/work/evaluation", "/evidence"}:
    raise SystemExit(f"unexpected mounts: {sorted(mounts)}")
if Path(mounts["/work/evaluation"]["Source"]).resolve() != Path(evaluation_dir).resolve():
    raise SystemExit("evaluation mount source mismatch")
if mounts["/work/evaluation"]["RW"]:
    raise SystemExit("evaluation mount must be read-only")
if Path(mounts["/evidence"]["Source"]).resolve() != Path(evidence_dir).resolve():
    raise SystemExit("evidence mount source mismatch")
if not mounts["/evidence"]["RW"]:
    raise SystemExit("evidence mount must be writable")

command = " ".join(config.get("Cmd") or [])
if "timeout --signal=TERM --kill-after=5s 43200s" not in command:
    raise SystemExit("43200-second task timeout is missing")
if "tools/validate_package.py . --public-only" not in command:
    raise SystemExit("container command is not scoped to public evaluation validation")

for key, value in expected.items():
    print(f"{key}={value}")
print("DeviceRequests=null")
print("CapDrop=ALL")
print("SecurityOpt=no-new-privileges")
print("EvaluationMount=read-only")
print("EvidenceMount=read-write")
print("TimeoutSeconds=43200")
PY

docker --context "$DOCKER_CONTEXT" start "$CONTAINER_NAME" >/dev/null

set +e
timeout --signal=TERM --kill-after=10s "${HOST_TIMEOUT_SECONDS}s" \
  docker --context "$DOCKER_CONTEXT" wait "$CONTAINER_NAME" \
  >"$EVIDENCE_DIR/container-exit-code.txt"
WAIT_STATUS=$?
set -e

if [[ "$WAIT_STATUS" -eq 124 ]]; then
  docker --context "$DOCKER_CONTEXT" kill "$CONTAINER_NAME" >/dev/null 2>&1 || true
  die "host timed out waiting for the evaluation container"
fi
[[ "$WAIT_STATUS" -eq 0 ]] || die "docker wait failed with status $WAIT_STATUS"

docker --context "$DOCKER_CONTEXT" logs "$CONTAINER_NAME" \
  >"$EVIDENCE_DIR/container-stdout.log" \
  2>"$EVIDENCE_DIR/container-stderr.log" || true
docker --context "$DOCKER_CONTEXT" inspect "$CONTAINER_NAME" \
  >"$EVIDENCE_DIR/container-inspect-post.json"

CONTAINER_EXIT="$(tr -d '\r\n ' < "$EVIDENCE_DIR/container-exit-code.txt")"
[[ "$CONTAINER_EXIT" =~ ^[0-9]+$ ]] || die "invalid container exit code: $CONTAINER_EXIT"

if [[ "$CONTAINER_EXIT" != "0" ]]; then
  cat "$EVIDENCE_DIR/container-stderr.log" >&2 || true
  die "evaluation container exited with status $CONTAINER_EXIT"
fi

python3 - \
  "$EVIDENCE_DIR/package-validation.json" \
  "$EXPECTED_PUBLIC_TASKS" <<'PY' \
  | tee "$EVIDENCE_DIR/validation-summary.txt"
import json
import sys
from pathlib import Path

report = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
expected_tasks = int(sys.argv[2])
smoke = report.get("smoke_tests", [])
errors = report.get("errors", [])
passed = [item for item in smoke if item.get("passed")]

if report.get("status") != "PASS":
    raise SystemExit(f"validation status is not PASS: {report.get('status')!r}")
if report.get("tasks_found") != expected_tasks:
    raise SystemExit(
        f"expected {expected_tasks} public tasks, found {report.get('tasks_found')!r}"
    )
if len(smoke) != expected_tasks or len(passed) != expected_tasks:
    raise SystemExit(
        f"expected {expected_tasks}/{expected_tasks} smoke tests, "
        f"got {len(passed)}/{len(smoke)}"
    )
if errors:
    raise SystemExit(f"validation reported errors: {errors!r}")

print(f"benchmark_version={report.get('benchmark_version')}")
print(f"tasks_found={report.get('tasks_found')}")
print(f"smoke_passed={len(passed)}")
print(f"errors={len(errors)}")
print(f"status={report.get('status')}")
PY

REPOSITORY_COMMIT="unversioned"
REPOSITORY_BRANCH="unversioned"
if command -v git >/dev/null 2>&1 && git -C "$REPOSITORY_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  REPOSITORY_COMMIT="$(git -C "$REPOSITORY_DIR" rev-parse HEAD)"
  REPOSITORY_BRANCH="$(git -C "$REPOSITORY_DIR" branch --show-current)"
fi

cat >"$EVIDENCE_DIR/run-summary.txt" <<EOF
timestamp_utc=$STAMP
repository=$REPOSITORY_DIR
branch=$REPOSITORY_BRANCH
commit=$REPOSITORY_COMMIT
docker_context=$DOCKER_CONTEXT
cgroup_version=$CGROUP_VERSION
image=$TEST_IMAGE
image_id=$IMAGE_ID
cpu_limit=$CPU_LIMIT
memory_limit=$MEMORY_LIMIT
memory_swap_limit=$MEMORY_SWAP_LIMIT
pids_limit=$PIDS_LIMIT
gpu=none
network=none
timeout_seconds=$TASK_TIMEOUT_SECONDS
container_exit=$CONTAINER_EXIT
evidence_dir=$EVIDENCE_DIR
EOF

(
  cd "$EVIDENCE_DIR"
  find . -maxdepth 1 -type f ! -name SHA256SUMS -print0 \
    | sort -z \
    | xargs -0 sha256sum > SHA256SUMS
  sha256sum -c SHA256SUMS
)

docker --context "$DOCKER_CONTEXT" rm "$CONTAINER_NAME" >/dev/null
CONTAINER_CREATED=0
trap - EXIT INT TERM

printf '\nPASS: evaluation Public Q01-Q08\n'
printf 'Evidence: %s\n' "$EVIDENCE_DIR"
