#!/bin/sh
set -eu

readonly CONFIG=/opt/model-gateway/opencode.json
readonly POLICY=/opt/model-gateway/model-policy.json

export OPENCODE_CONFIG="$CONFIG"
export OPENCODE_DISABLE_AUTOUPDATE=true

mode="${1:-probe}"
case "$mode" in
  probe)
    exec python3 /opt/model-gateway/probe.py "$POLICY" "$CONFIG"
    ;;
  invoke)
    model="${2:-}"
    case "$model" in
      alibaba-token-plan-cn/qwen3.8-max|alibaba-token-plan-cn/qwen3-vl-plus|alibaba-token-plan-cn/glm-5.2)
        ;;
      *)
        printf 'ERROR: unsupported OpenCode model: %s\n' "$model" >&2
        exit 64
        ;;
    esac
    if [ ! -s /run/secrets/qwen_api_key ]; then
      printf 'ERROR: /run/secrets/qwen_api_key is missing or empty\n' >&2
      exit 65
    fi
    ALIBABA_TOKEN_PLAN_API_KEY="$(cat /run/secrets/qwen_api_key)"
    export ALIBABA_TOKEN_PLAN_API_KEY
    exec opencode run --agent gateway-smoke --model "$model" \
      'This is a model gateway smoke test. Reply with exactly MODEL_GATEWAY_OK and nothing else.'
    ;;
  *)
    printf 'ERROR: mode must be probe or invoke\n' >&2
    exit 64
    ;;
esac
