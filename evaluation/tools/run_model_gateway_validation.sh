#!/usr/bin/env bash
# Validate the competition gateway/model policy in a network-restricted Docker pair.

set -Eeuo pipefail

readonly CPU_LIMIT="2"
readonly MEMORY_LIMIT="4g"
readonly MEMORY_SWAP_LIMIT="4g"
readonly PIDS_LIMIT="256"
readonly MAX_RUNTIME_SECONDS="43200"
readonly HOST_TIMEOUT_SECONDS="43230"

DOCKER_CONTEXT="${DOCKER_CONTEXT:-default}"
EVIDENCE_DIR="${EVIDENCE_DIR:-}"
WORKER_IMAGE="${WORKER_IMAGE:-gga-model-gateway-worker:1.18.14}"
PROXY_IMAGE="${PROXY_IMAGE:-gga-model-gateway-proxy:bookworm}"
MODE="probe"
MODEL_ID="qwen3.8-max"
API_KEY_FILE=""
CONFIRM_PRIMARY_UNAVAILABLE=0
BUILD_IMAGES=1

usage() {
  cat <<'EOF'
Usage: bash tools/run_model_gateway_validation.sh [options]

Default behavior performs a credential-free Docker probe:
  - validates Gateway and Qwen Base URL with normal TLS verification;
  - proves that only the two frozen domains are reachable through the proxy;
  - validates Qwen3.8-Max as primary and the exact fallback policy;
  - verifies 2 CPU / 4 GiB / 256 PID / no-GPU / 12-hour maximum limits.

Options:
  --context NAME              Docker context (default: default)
  --evidence-dir PATH         Evidence output directory
  --skip-build                Reuse existing worker/proxy images
  --invoke-primary            Run one minimal OpenCode call with qwen3.8-max
  --invoke-fallback MODEL     Run qwen3-vl-plus or glm-5.2
  --confirm-primary-unavailable
                              Required with --invoke-fallback; operator confirms
                              the official primary service is unavailable
  --api-key-file PATH         Token Plan API key file; mounted read-only as a
                              Docker secret and never placed in container env
  -h, --help                  Show this help

Wan2.7-Image-Pro is recorded in the routing policy but is not sent to the
Anthropic Messages endpoint. Image generation must use the evaluator-managed
image route supplied by the competition gateway.
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
    --evidence-dir)
      [[ $# -ge 2 ]] || die "--evidence-dir requires a value"
      EVIDENCE_DIR="$2"
      shift 2
      ;;
    --skip-build)
      BUILD_IMAGES=0
      shift
      ;;
    --invoke-primary)
      MODE="invoke"
      MODEL_ID="qwen3.8-max"
      shift
      ;;
    --invoke-fallback)
      [[ $# -ge 2 ]] || die "--invoke-fallback requires a model ID"
      MODE="invoke-fallback"
      MODEL_ID="$2"
      shift 2
      ;;
    --confirm-primary-unavailable)
      CONFIRM_PRIMARY_UNAVAILABLE=1
      shift
      ;;
    --api-key-file)
      [[ $# -ge 2 ]] || die "--api-key-file requires a path"
      API_KEY_FILE="$2"
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
require_command timeout
require_command sha256sum
require_command find
require_command sort
require_command xargs

[[ "$(uname -s)" == "Linux" ]] || die "this runner requires Linux"

case "$MODE:$MODEL_ID" in
  probe:qwen3.8-max|invoke:qwen3.8-max)
    ;;
  invoke-fallback:qwen3-vl-plus|invoke-fallback:glm-5.2)
    [[ "$CONFIRM_PRIMARY_UNAVAILABLE" -eq 1 ]] || \
      die "fallback requires --confirm-primary-unavailable"
    ;;
  *)
    die "unsupported model/mode combination: $MODE:$MODEL_ID"
    ;;
esac

if [[ "$MODE" != "probe" ]]; then
  [[ -n "$API_KEY_FILE" ]] || die "model invocation requires --api-key-file"
  [[ -f "$API_KEY_FILE" && ! -L "$API_KEY_FILE" && -s "$API_KEY_FILE" ]] || \
    die "API key must be a non-empty, non-symlink regular file"
  API_KEY_FILE="$(cd -- "$(dirname -- "$API_KEY_FILE")" && pwd -P)/$(basename -- "$API_KEY_FILE")"
  [[ -r "$API_KEY_FILE" ]] || die "API key file is not readable by the current user"
fi

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
EVALUATION_DIR="$(cd -- "$SCRIPT_DIR/.." && pwd -P)"
REPOSITORY_DIR="$(cd -- "$EVALUATION_DIR/.." && pwd -P)"
CONTEXT_DIR="$EVALUATION_DIR/model_gateway"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_SUFFIX="${STAMP,,}-$$"

if [[ -z "$EVIDENCE_DIR" ]]; then
  EVIDENCE_DIR="${HOME}/evaluation-test-evidence/model-gateway-${STAMP}"
fi
mkdir -p "$EVIDENCE_DIR"
EVIDENCE_DIR="$(cd -- "$EVIDENCE_DIR" && pwd -P)"
case "$EVIDENCE_DIR/" in
  "$REPOSITORY_DIR/"*) die "evidence directory must be outside the repository" ;;
esac

INTERNAL_NETWORK="gga-model-internal-${RUN_SUFFIX}"
EGRESS_NETWORK="gga-model-egress-${RUN_SUFFIX}"
PROXY_CONTAINER="gga-model-proxy-${RUN_SUFFIX}"
WORKER_CONTAINER="gga-model-worker-${RUN_SUFFIX}"
INTERNAL_CREATED=0
EGRESS_CREATED=0
PROXY_CREATED=0
WORKER_CREATED=0

cleanup() {
  local status=$?
  trap - EXIT INT TERM
  if [[ "$WORKER_CREATED" -eq 1 ]]; then
    docker --context "$DOCKER_CONTEXT" rm -f "$WORKER_CONTAINER" >/dev/null 2>&1 || true
  fi
  if [[ "$PROXY_CREATED" -eq 1 ]]; then
    docker --context "$DOCKER_CONTEXT" rm -f "$PROXY_CONTAINER" >/dev/null 2>&1 || true
  fi
  if [[ "$INTERNAL_CREATED" -eq 1 ]]; then
    docker --context "$DOCKER_CONTEXT" network rm "$INTERNAL_NETWORK" >/dev/null 2>&1 || true
  fi
  if [[ "$EGRESS_CREATED" -eq 1 ]]; then
    docker --context "$DOCKER_CONTEXT" network rm "$EGRESS_NETWORK" >/dev/null 2>&1 || true
  fi
  exit "$status"
}
trap cleanup EXIT INT TERM

printf 'Repository: %s\n' "$REPOSITORY_DIR"
printf 'Mode: %s\n' "$MODE"
printf 'Model: %s\n' "$MODEL_ID"
printf 'Evidence: %s\n' "$EVIDENCE_DIR"

docker --context "$DOCKER_CONTEXT" version >"$EVIDENCE_DIR/docker-version.txt"
docker --context "$DOCKER_CONTEXT" info >"$EVIDENCE_DIR/docker-info.txt"
CGROUP_VERSION="$(docker --context "$DOCKER_CONTEXT" info --format '{{.CgroupVersion}}')"
[[ "$CGROUP_VERSION" == "2" ]] || die "Docker must use cgroup v2"

if [[ "$BUILD_IMAGES" -eq 1 ]]; then
  docker --context "$DOCKER_CONTEXT" build \
    --file "$CONTEXT_DIR/Dockerfile.proxy" \
    --tag "$PROXY_IMAGE" \
    "$CONTEXT_DIR" >"$EVIDENCE_DIR/proxy-build.log" 2>&1 || \
    die "proxy image build failed; see $EVIDENCE_DIR/proxy-build.log"
  docker --context "$DOCKER_CONTEXT" build \
    --file "$CONTEXT_DIR/Dockerfile" \
    --tag "$WORKER_IMAGE" \
    "$CONTEXT_DIR" >"$EVIDENCE_DIR/worker-build.log" 2>&1 || \
    die "worker image build failed; see $EVIDENCE_DIR/worker-build.log"
fi

docker --context "$DOCKER_CONTEXT" image inspect "$PROXY_IMAGE" \
  >"$EVIDENCE_DIR/proxy-image-inspect.json"
docker --context "$DOCKER_CONTEXT" image inspect "$WORKER_IMAGE" \
  >"$EVIDENCE_DIR/worker-image-inspect.json"

docker --context "$DOCKER_CONTEXT" network create \
  --internal \
  --label io.hackathon.evaluation=model-gateway \
  "$INTERNAL_NETWORK" >"$EVIDENCE_DIR/internal-network-id.txt"
INTERNAL_CREATED=1
docker --context "$DOCKER_CONTEXT" network create \
  --label io.hackathon.evaluation=model-gateway-egress \
  "$EGRESS_NETWORK" >"$EVIDENCE_DIR/egress-network-id.txt"
EGRESS_CREATED=1

docker --context "$DOCKER_CONTEXT" create \
  --name "$PROXY_CONTAINER" \
  --network "$EGRESS_NETWORK" \
  --network-alias model-egress \
  --cpus 0.5 \
  --memory 256m \
  --memory-swap 256m \
  --pids-limit 128 \
  --read-only \
  --tmpfs /tmp:rw,nosuid,nodev,noexec,size=32m,mode=1777 \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --restart=no \
  --label io.hackathon.e1.role=allowlist-egress \
  "$PROXY_IMAGE" >"$EVIDENCE_DIR/proxy-container-id.txt"
PROXY_CREATED=1
docker --context "$DOCKER_CONTEXT" start "$PROXY_CONTAINER" >/dev/null
docker --context "$DOCKER_CONTEXT" network connect \
  --alias model-egress "$INTERNAL_NETWORK" "$PROXY_CONTAINER"

worker_args=(
  docker --context "$DOCKER_CONTEXT" create
  --name "$WORKER_CONTAINER"
  --network "$INTERNAL_NETWORK"
  --cpus "$CPU_LIMIT"
  --memory "$MEMORY_LIMIT"
  --memory-swap "$MEMORY_SWAP_LIMIT"
  --pids-limit "$PIDS_LIMIT"
  --read-only
  --tmpfs /tmp:rw,nosuid,nodev,noexec,size=256m,mode=1777
  --tmpfs /state:rw,nosuid,nodev,size=512m,mode=0700,uid=1000,gid=1000
  --cap-drop ALL
  --security-opt no-new-privileges
  --restart=no
  --user 1000:1000
  --env HOME=/state
  --env XDG_DATA_HOME=/state/data
  --env XDG_CACHE_HOME=/state/cache
  --env XDG_CONFIG_HOME=/state/config
  --env HTTP_PROXY=http://model-egress:3128
  --env HTTPS_PROXY=http://model-egress:3128
  --env http_proxy=http://model-egress:3128
  --env https_proxy=http://model-egress:3128
  --env NO_PROXY=localhost,127.0.0.1
  --env no_proxy=localhost,127.0.0.1
  --env CUDA_VISIBLE_DEVICES=
  --env NVIDIA_VISIBLE_DEVICES=void
  --mount "type=bind,src=$REPOSITORY_DIR,dst=/workspace,readonly"
  --workdir /workspace
)
if [[ "$MODE" != "probe" ]]; then
  worker_args+=(--mount "type=bind,src=$API_KEY_FILE,dst=/run/secrets/qwen_api_key,readonly")
fi
worker_args+=("$WORKER_IMAGE")
if [[ "$MODE" == "probe" ]]; then
  worker_args+=(probe)
else
  worker_args+=(invoke "alibaba-token-plan-cn/$MODEL_ID")
fi

"${worker_args[@]}" >"$EVIDENCE_DIR/worker-container-id.txt"
WORKER_CREATED=1
docker --context "$DOCKER_CONTEXT" inspect "$WORKER_CONTAINER" \
  >"$EVIDENCE_DIR/worker-inspect-pre.json"
docker --context "$DOCKER_CONTEXT" inspect "$PROXY_CONTAINER" \
  >"$EVIDENCE_DIR/proxy-inspect-pre.json"
docker --context "$DOCKER_CONTEXT" network inspect "$INTERNAL_NETWORK" \
  >"$EVIDENCE_DIR/internal-network-inspect.json"
docker --context "$DOCKER_CONTEXT" network inspect "$EGRESS_NETWORK" \
  >"$EVIDENCE_DIR/egress-network-inspect.json"

python3 - \
  "$EVIDENCE_DIR/worker-inspect-pre.json" \
  "$EVIDENCE_DIR/proxy-inspect-pre.json" \
  "$EVIDENCE_DIR/internal-network-inspect.json" \
  "$INTERNAL_NETWORK" \
  "$REPOSITORY_DIR" \
  "$MODE" <<'PY' | tee "$EVIDENCE_DIR/resource-contract.txt"
import json
import sys
from pathlib import Path

worker_path, proxy_path, network_path, internal_name, repository, mode = sys.argv[1:]
worker = json.loads(Path(worker_path).read_text(encoding="utf-8"))[0]
proxy = json.loads(Path(proxy_path).read_text(encoding="utf-8"))[0]
network = json.loads(Path(network_path).read_text(encoding="utf-8"))[0]
host = worker["HostConfig"]
config = worker["Config"]

expected = {
    "NanoCpus": 2_000_000_000,
    "Memory": 4_294_967_296,
    "MemorySwap": 4_294_967_296,
    "PidsLimit": 256,
    "NetworkMode": internal_name,
    "ReadonlyRootfs": True,
}
for key, value in expected.items():
    if host.get(key) != value:
        raise SystemExit(f"worker contract mismatch: {key}={host.get(key)!r}, expected {value!r}")
if host.get("DeviceRequests") not in (None, []):
    raise SystemExit("worker GPU requests are forbidden")
if "ALL" not in (host.get("CapDrop") or []):
    raise SystemExit("worker must drop all capabilities")
if "no-new-privileges" not in (host.get("SecurityOpt") or []):
    raise SystemExit("worker must enable no-new-privileges")
if config.get("User") != "1000:1000":
    raise SystemExit("worker user must be 1000:1000")

env = dict(item.split("=", 1) for item in config.get("Env", []) if "=" in item)
if env.get("NVIDIA_VISIBLE_DEVICES") != "void" or env.get("CUDA_VISIBLE_DEVICES") != "":
    raise SystemExit("worker GPU environment is not disabled")
if "QWEN_API_KEY" in env or "ALIBABA_TOKEN_PLAN_API_KEY" in env:
    raise SystemExit("API key leaked into Docker inspect environment")
if env.get("HTTPS_PROXY") != "http://model-egress:3128":
    raise SystemExit("worker is not bound to the allowlist proxy")

mounts = {item["Destination"]: item for item in worker.get("Mounts", [])}
workspace = mounts.get("/workspace")
if not workspace or workspace.get("RW") is not False:
    raise SystemExit("workspace must be mounted read-only")
if Path(workspace["Source"]).resolve() != Path(repository).resolve():
    raise SystemExit("workspace source mismatch")
secret = mounts.get("/run/secrets/qwen_api_key")
if mode == "probe" and secret is not None:
    raise SystemExit("probe mode must not mount a credential")
if mode != "probe" and (not secret or secret.get("RW") is not False):
    raise SystemExit("invoke mode must mount the credential read-only")

proxy_host = proxy["HostConfig"]
if proxy_host.get("ReadonlyRootfs") is not True:
    raise SystemExit("proxy root filesystem must be read-only")
if "ALL" not in (proxy_host.get("CapDrop") or []):
    raise SystemExit("proxy must drop all capabilities")
if "no-new-privileges" not in (proxy_host.get("SecurityOpt") or []):
    raise SystemExit("proxy must enable no-new-privileges")
if network.get("Internal") is not True:
    raise SystemExit("candidate network must be internal")
worker_networks = (worker.get("NetworkSettings") or {}).get("Networks") or {}
proxy_networks = (proxy.get("NetworkSettings") or {}).get("Networks") or {}
if set(worker_networks) != {internal_name}:
    raise SystemExit("worker has direct or unexpected network attachment")
if internal_name not in proxy_networks or len(proxy_networks) != 2:
    raise SystemExit("proxy must bridge exactly one internal and one egress network")

print("resource_contract=PASS")
for key, value in expected.items():
    print(f"{key}={value}")
print("DeviceRequests=null")
print("GPU=none")
print("DirectCandidateEgress=none")
print("ProxyAllowlist=2 domains")
print("CredentialInInspect=no")
print("MaxRuntimeSeconds=43200")
PY

docker --context "$DOCKER_CONTEXT" start "$WORKER_CONTAINER" >/dev/null
set +e
timeout --signal=TERM --kill-after=10s "${HOST_TIMEOUT_SECONDS}s" \
  docker --context "$DOCKER_CONTEXT" wait "$WORKER_CONTAINER" \
  >"$EVIDENCE_DIR/worker-exit-code.txt"
WAIT_STATUS=$?
set -e
if [[ "$WAIT_STATUS" -eq 124 ]]; then
  docker --context "$DOCKER_CONTEXT" kill "$WORKER_CONTAINER" >/dev/null 2>&1 || true
  die "host timed out after the 12-hour maximum"
fi
[[ "$WAIT_STATUS" -eq 0 ]] || die "docker wait failed with status $WAIT_STATUS"

docker --context "$DOCKER_CONTEXT" logs "$WORKER_CONTAINER" \
  >"$EVIDENCE_DIR/worker-stdout.log" \
  2>"$EVIDENCE_DIR/worker-stderr.log" || true
docker --context "$DOCKER_CONTEXT" logs "$PROXY_CONTAINER" \
  >"$EVIDENCE_DIR/proxy-stdout.log" \
  2>"$EVIDENCE_DIR/proxy-stderr.log" || true
docker --context "$DOCKER_CONTEXT" inspect "$WORKER_CONTAINER" \
  >"$EVIDENCE_DIR/worker-inspect-post.json"

CONTAINER_EXIT="$(tr -d '\r\n ' < "$EVIDENCE_DIR/worker-exit-code.txt")"
[[ "$CONTAINER_EXIT" == "0" ]] || {
  tail -n 100 "$EVIDENCE_DIR/worker-stderr.log" >&2 || true
  die "model gateway worker exited with status $CONTAINER_EXIT"
}

if [[ "$MODE" == "probe" ]]; then
  grep -Fx 'policy_validation=PASS' "$EVIDENCE_DIR/worker-stdout.log" >/dev/null || \
    die "policy probe did not pass"
  grep -Fx 'tls_verification=PASS' "$EVIDENCE_DIR/worker-stdout.log" >/dev/null || \
    die "TLS probe did not pass"
  grep -Fx 'non_allowlisted_egress=BLOCKED' "$EVIDENCE_DIR/worker-stdout.log" >/dev/null || \
    die "non-allowlisted egress was not blocked"
else
  grep -F 'MODEL_GATEWAY_OK' "$EVIDENCE_DIR/worker-stdout.log" >/dev/null || \
    die "OpenCode model response did not contain MODEL_GATEWAY_OK"
fi

cat >"$EVIDENCE_DIR/run-summary.txt" <<EOF
timestamp_utc=$STAMP
mode=$MODE
model_id=$MODEL_ID
credential_used=$([[ "$MODE" == "probe" ]] && printf no || printf yes)
docker_context=$DOCKER_CONTEXT
cgroup_version=$CGROUP_VERSION
worker_image=$WORKER_IMAGE
proxy_image=$PROXY_IMAGE
cpu_limit=$CPU_LIMIT
memory_limit=$MEMORY_LIMIT
memory_swap_limit=$MEMORY_SWAP_LIMIT
pids_limit=$PIDS_LIMIT
gpu=none
candidate_network=internal_proxy_only
allowlist_domains=ai.chipcloud.cc,token-plan.cn-beijing.maas.aliyuncs.com
max_runtime_seconds=$MAX_RUNTIME_SECONDS
container_exit=$CONTAINER_EXIT
status=PASS
EOF

(
  cd "$EVIDENCE_DIR"
  find . -maxdepth 1 -type f ! -name SHA256SUMS -print0 \
    | sort -z \
    | xargs -0 sha256sum > SHA256SUMS
  sha256sum -c SHA256SUMS
)

docker --context "$DOCKER_CONTEXT" rm "$WORKER_CONTAINER" >/dev/null
WORKER_CREATED=0
docker --context "$DOCKER_CONTEXT" rm -f "$PROXY_CONTAINER" >/dev/null
PROXY_CREATED=0
docker --context "$DOCKER_CONTEXT" network rm "$INTERNAL_NETWORK" >/dev/null
INTERNAL_CREATED=0
docker --context "$DOCKER_CONTEXT" network rm "$EGRESS_NETWORK" >/dev/null
EGRESS_CREATED=0
trap - EXIT INT TERM

printf '\nPASS: Docker model gateway %s (%s)\n' "$MODE" "$MODEL_ID"
printf 'Evidence: %s\n' "$EVIDENCE_DIR"
