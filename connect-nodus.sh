#!/usr/bin/env bash
# Usage: ./connect-nodus.sh
#
# Connects Nodus inference (https://www.nodus-compute.ai) to the Reason workspace of
# REASON_API_KEY as its Custom provider, so a run can use a Nodus-hosted model:
#   MODEL=byok:custom-endpoint:zai-org/glm-5.3 EFFORT=high ./run.sh deepswe
# The sandboxes stay on e2b, Modal or Docker; Nodus serves only the model calls.
#
# Needs NODUS_API_KEY (scope inference:invoke is enough) and a REASON_API_KEY with org:write.
# NODUS_MODELS picks the models offered (comma-separated Nodus model ids). Running it again
# replaces the workspace's Custom provider with this one.
set -euo pipefail

fail() { printf '%s\n' "$1" >&2; exit 2; }
: "${REASON_API_KEY:?Set REASON_API_KEY (needs the org:write scope)}"
: "${NODUS_API_KEY:?Set NODUS_API_KEY (a Nodus inference key)}"
command -v python3 >/dev/null || fail "Needs python3"

api=${REASON_API_ORIGIN:-https://api.reasonmachines.com}
base_url=${NODUS_BASE_URL:-https://platform-inference.nodus-compute.ai/v1}
models=${NODUS_MODELS:-zai-org/glm-5.3,moonshotai/kimi-k3,deepseek-ai/deepseek-v4-pro}

# Every listed model must be served to this key, or a run would fail on its first call.
served=$(curl -fsS -m 30 -H "Authorization: Bearer $NODUS_API_KEY" "$base_url/models") \
  || fail "Nodus refused NODUS_API_KEY at $base_url/models"
NODUS_SERVED=$served python3 - "$models" <<'PY' || exit 2
import json, os, sys
served = {m["id"] for m in json.loads(os.environ["NODUS_SERVED"])["data"]}
missing = [m for m in sys.argv[1].split(",") if m not in served]
if missing:
    sys.exit(f"Nodus doesn't serve {', '.join(missing)} to this key")
PY

org=$(curl -fsS -m 30 -H "Authorization: Bearer $REASON_API_KEY" "$api/v3/self" \
  | python3 -c 'import json, sys; print(json.load(sys.stdin)["org_id"])') \
  || fail "Reason refused REASON_API_KEY"

# Each listed model accepts tools and reasoning effort over Nodus's OpenAI-compatible
# Chat Completions API; the smallest context window among them is 1M tokens.
body=$(NODUS_MODELS_LIST=$models BASE_URL=$base_url python3 -c '
import json, os
models = os.environ["NODUS_MODELS_LIST"]
print(json.dumps({"key": os.environ["NODUS_API_KEY"], "config": {
    "CUSTOM_ENDPOINT_NAME": "Nodus",
    "CUSTOM_ENDPOINT_EXECUTION": "cloud",
    "CUSTOM_ENDPOINT_BASE_URL": os.environ["BASE_URL"],
    "CUSTOM_ENDPOINT_API": "openai-completions",
    "CUSTOM_ENDPOINT_MODELS": models,
    "CUSTOM_ENDPOINT_REASONING_MODELS": models,
    "CUSTOM_ENDPOINT_REASONING_EFFORTS": "low,medium,high",
    "CUSTOM_ENDPOINT_CONTEXT_WINDOW_TOKENS": "1000000",
    "CUSTOM_ENDPOINT_MAX_OUTPUT_TOKENS": "65536",
}}))')
# The key travels on stdin, never in the process list.
printf '%s' "$body" | curl -fsS -m 60 -X PUT -o /dev/null \
  -H "Authorization: Bearer $REASON_API_KEY" -H "content-type: application/json" \
  --data-binary @- "$api/v3/organizations/$org/provider-credentials/custom-endpoint" \
  || fail "Reason refused the Custom provider (REASON_API_KEY needs org:write)"

echo "Connected Nodus to workspace $org. Run with one of:"
for model in ${models//,/ }; do echo "  MODEL=byok:custom-endpoint:$model"; done
