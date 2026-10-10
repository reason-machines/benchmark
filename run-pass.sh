#!/usr/bin/env bash
# Usage: ./run-pass.sh MODEL EFFORT        e.g. ./run-pass.sh openai/gpt-6-luna xhigh
#                                          or ./run-pass.sh byok:openai:gpt-6-luna xhigh
#        ./run-pass.sh oracle|nop          the preflight, on the same environments
#
# One pass: every task of all three benchmarks, ATTEMPTS attempts each (default 3), for one
# configuration (a model at one reasoning effort) on one harness: the adapter's default
# dated Reason release, which never changes (runtime/reason-v7-2026-10), or HARNESS
# (runtime/reason-c2-tools-v7 runs the deployment's current default harness, which
# moves with every deploy). Tasks run on e2b
# (up to 80 sandboxes) and, for the tasks listed in <benchmark>/modal-tasks.txt, on Modal
# (up to 10 sandboxes) at the same time. Results go to jobs/<model>-<effort>/, logs and a
# manifest of what ran to logs/.
#
# The preflight runs Harbor's oracle agent (each task's reference solution) or nop agent
# (no work) once per task instead, into jobs/<agent>-<time>/. It passes when score.py
# --expect finds every task at 1 for oracle and 0 for nop, which shows each environment
# grades a task as the task's authors do.
set -euo pipefail

usage() { sed -n 2,4p "$0" >&2; exit 2; }
stamp=$(date -u +%Y%m%dT%H%M%SZ)
case "${1:-}" in
  oracle|nop)
    [ "$#" -eq 1 ] || usage
    model=$1 effort=none preflight=1 attempts=1 pass="$1-$stamp" ;;
  *)
    [ "$#" -eq 2 ] || usage
    model=$1 effort=$2 preflight="" attempts=${ATTEMPTS:-3}
    case "$effort" in minimal|low|medium|high|xhigh|max) ;; *) echo "EFFORT must be minimal, low, medium, high, xhigh or max" >&2; exit 2 ;; esac
    pass="$(printf %s "${model##*/}" | tr : -)-$effort" ;;
esac

benchmarks="deepswe swe-atlas-qna terminal-bench"
e2b_sandboxes=80
modal_sandboxes=10
root=$(cd -- "$(dirname -- "$0")" && pwd)
grader=claude-opus-4-5-20251101
harness=${HARNESS:-}

[ -n "$preflight" ] || : "${REASON_API_KEY:?Set REASON_API_KEY (see README.md)}"
: "${ANTHROPIC_API_KEY:?Set ANTHROPIC_API_KEY; it grades SWE-Atlas QnA (see README.md)}"
: "${E2B_API_KEY:?Set E2B_API_KEY (see README.md)}"
command -v harbor >/dev/null || { echo 'Install Harbor first (see README.md)' >&2; exit 2; }
[ -n "${MODAL_TOKEN_ID:-}" ] || [ -f "$HOME/.modal.toml" ] || { echo "Log in to Modal: uvx modal token new" >&2; exit 2; }

# Registry digests pin the exact task sets.
dataset() {
  case "$1" in
    deepswe) echo "datacurve/deep-swe-1-1@sha256:5affcd534fd90ac85d202d4c63f8b35ddc942140afdd5d60014a21365440a2f5" ;;
    swe-atlas-qna) echo "scale-ai/swe-atlas-qna@sha256:0e26bc0313ae2fc6f912b67b928e648c7f20d17d91f765f702a93042ce5be0e4" ;;
    terminal-bench) echo "terminal-bench/terminal-bench@sha256:39d9f44b40420cde8fdcc087579c0d72a7e14fa3656d603c3f0d22fb35e27732" ;;
  esac
}

# A Modal sandbox may live for the task's agent, setup and grading budgets plus 30 minutes.
lifetime() {
  case "$1" in deepswe) echo 10800 ;; swe-atlas-qna) echo 15300 ;; terminal-bench) echo 34200 ;; esac
}

# One Harbor job: one benchmark on one environment.
harbor_job() {
  local bench=$1 env=$2 flag concurrency harbor_env task
  shift 2
  # e2b drops the image's ENV; the adapter's environment (0.3.16+) passes it to the sandbox, PATH included.
  if [ "$env" = e2b ]; then flag=-x concurrency=$e2b_sandboxes harbor_env=reasonmachines_harbor.environment:ReasonE2BEnvironment
  else flag=-i concurrency=$modal_sandboxes harbor_env=modal; fi
  local agent=(--agent "$model")
  if [ -z "$preflight" ]; then
    agent=(
      --agent reasonmachines_harbor:ReasonAgent
      --model "$model"
      --ak "reasoning_effort=$effort"
      --ak mode=ephemeral
      --allow-agent-host api.reasonmachines.com
      --allow-agent-host relay.reasonmachines.com
    )
    [ -z "$harness" ] || agent+=(--ak "runtime_profile=$harness")
  fi
  local args=(
    --dataset "$(dataset "$bench")"
    "${agent[@]}"
    --env "$harbor_env" --n-attempts "$attempts" --n-concurrent "$concurrency"
    # Infrastructure errors are retried; timeouts are results.
    --max-retries 3 --retry-exclude AgentTimeoutError --retry-exclude VerifierTimeoutError
    --enable-verification -y
    --jobs-dir "$root/jobs/$pass/$bench/$env" --job-name "$stamp"
  )
  if [ "$bench" = swe-atlas-qna ]; then
    # The grader is Claude Opus 4.5 through Anthropic's OpenAI-compatible API.
    args+=(--ve 'EVAL_API_KEY=${ANTHROPIC_API_KEY}' --ve EVAL_BASE_URL=https://api.anthropic.com/v1/
      --ve "EVAL_MODEL=$grader")
    # e2b stops at 8 CPUs / 8 GiB; both halves run at that size so they match.
    args+=(--override-cpus 8 --override-memory-mb 8192)
    # SWE-Atlas images set ENTRYPOINT ["/bin/bash"], so Modal's keep-alive is bash arguments.
    [ "$env" = e2b ] || args+=(--ek 'keepalive=["-c","sleep infinity"]')
  fi
  # e2b skips the Modal tasks; Modal runs only those.
  while read -r task; do
    case "$task" in ''|'#'*) continue ;; esac
    args+=("$flag" "$task")
  done < "$root/$bench/modal-tasks.txt"
  harbor run "${args[@]}" "$@"
}

# Every Modal job gets its own app with a hard sandbox lifetime, and is stopped when Harbor exits.
apps="$root/logs/$pass-$stamp.modal-apps"
guard() { uv run -q "$root/modal_guard.py" "$@"; }
modal_job() {
  local bench=$1 app="reason-bench-$stamp-$bench" pid status=0
  echo "$app" >> "$apps"
  guard fresh "$app"
  harbor_job "$bench" modal --ek "app_name=$app" --ek "sandbox_timeout_secs=$(lifetime "$bench")" &
  pid=$!
  guard watch "$pid" "$app" > "$root/logs/$app.guard.log" 2>&1 &
  wait "$pid" || status=$?
  guard stop "$app" || status=1
  return "$status"
}
stop_modal() { [ -f "$apps" ] || return 0; while read -r app; do guard stop "$app" || true; done < "$apps"; }
trap 'stop_modal; kill 0' INT TERM

mkdir -p "$root/logs"
log="$root/logs/$pass-$stamp"
harbor_python="$(dirname "$(readlink -f "$(command -v harbor)")")/python"
{
  echo "pass: $pass"
  echo "model: $model"
  echo "reasoning_effort: $effort"
  echo "attempts: $attempts"
  [ -n "$preflight" ] || echo "harness: ${harness:-$("$harbor_python" -c 'from reasonmachines_harbor._driver.driver import DEFAULT_EPHEMERAL_RUNTIME_PROFILE as d; print(d)' 2>/dev/null || echo unknown)}"
  echo "started: $stamp"
  for bench in $benchmarks; do
    echo "dataset_$bench: $(dataset "$bench")"
    echo "modal_tasks_$bench: $(grep -cvE '^(#|$)' "$root/$bench/modal-tasks.txt" || true) tasks, sha256 $(shasum -a 256 "$root/$bench/modal-tasks.txt" | cut -c1-16)"
  done
  echo "e2b_environment: reasonmachines_harbor.environment:ReasonE2BEnvironment"
  echo "swe_atlas_grader: $grader"
  echo "benchmark_commit: $(git -C "$root" rev-parse HEAD 2>/dev/null || echo unknown)"
  echo "harbor: $("$harbor_python" -c 'import importlib.metadata as m; print(m.version("harbor"))' 2>/dev/null || echo unknown)"
  echo "reason-machines-harbor: $("$harbor_python" -c 'import importlib.metadata as m; print(m.version("reason-machines-harbor"))' 2>/dev/null || echo unknown)"
  echo "e2b_sandboxes: $e2b_sandboxes"
  echo "modal_sandboxes: $modal_sandboxes"
} > "$log.manifest"
echo "Pass $pass: e2b -> $log.e2b.log, Modal -> $log.modal.log"

# The e2b half and the Modal half run at the same time; each runs the benchmarks in turn.
( status=0; for bench in $benchmarks; do harbor_job "$bench" e2b || status=1; done; exit "$status" ) > "$log.e2b.log" 2>&1 &
e2b_half=$!
( status=0; for bench in $benchmarks; do modal_job "$bench" || status=1; done; exit "$status" ) > "$log.modal.log" 2>&1 &
modal_half=$!
status=0
wait "$e2b_half" || status=1
wait "$modal_half" || status=1

echo "finished: $(date -u +%Y%m%dT%H%M%SZ)" >> "$log.manifest"
if [ -n "$preflight" ]; then
  expect=0; [ "$model" = nop ] || expect=1
  python3 "$root/score.py" --expect "$expect" "$root/jobs/$pass" | tee "$log.score.md" || status=1
  exit "$status"
fi
# Screen for reward hacking before scoring. SCREEN_JUDGE=1 also runs the paid judge (screening/screen.py).
judge=(); [ "${SCREEN_JUDGE:-0}" != 1 ] || judge=(--judge)
python3 "$root/screening/screen.py" ${judge[@]+"${judge[@]}"} "$root/jobs/$pass" > "$log.screening.md" || true
# --strict says whether the pass can be published yet: complete, on one configuration.
python3 "$root/score.py" --strict "$root/jobs/$pass" | tee "$log.score.md" || status=1
exit "$status"
