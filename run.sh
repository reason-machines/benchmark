#!/usr/bin/env bash
# Usage: ./run.sh deepswe|swe-atlas-qna|terminal-bench|all [extra harbor run arguments]
#
# By default each benchmark runs on e2b, and the tasks e2b can't host
# (<benchmark>/modal-tasks.txt) run on Modal at the same time. HARBOR_ENV=modal or
# HARBOR_ENV=docker runs every task there instead. Reason runs the adapter's default
# harness, a dated release that never changes (runtime/reason-v7-2026-10), unless HARNESS
# names another. Results go to jobs/<run>/.
set -euo pipefail

# Registry digests pin the exact task set we ran.
dataset() {
  case "$1" in
    deepswe) echo "datacurve/deep-swe-1-1@sha256:5affcd534fd90ac85d202d4c63f8b35ddc942140afdd5d60014a21365440a2f5" ;;
    swe-atlas-qna) echo "scale-ai/swe-atlas-qna@sha256:0e26bc0313ae2fc6f912b67b928e648c7f20d17d91f765f702a93042ce5be0e4" ;;
    terminal-bench) echo "terminal-bench/terminal-bench@sha256:39d9f44b40420cde8fdcc087579c0d72a7e14fa3656d603c3f0d22fb35e27732" ;;
  esac
}

fail() { printf '%s\n' "$1" >&2; exit 2; }
if [ "$#" -lt 1 ]; then sed -n 2p "$0" >&2; exit 2; fi
target=$1; shift
case "$target" in
  all) benchmarks="deepswe swe-atlas-qna terminal-bench" ;;
  deepswe|swe-atlas-qna|terminal-bench) benchmarks=$target ;;
  *) sed -n 2p "$0" >&2; exit 2 ;;
esac
extra=("$@")

model=${MODEL:-openai/gpt-6-luna}
effort=${EFFORT:-xhigh}
environment=${HARBOR_ENV:-e2b}
part=${PART:-both}
case "$effort" in minimal|low|medium|high|xhigh|max) ;; *) fail "EFFORT must be minimal, low, medium, high, xhigh or max" ;; esac
case "$environment" in e2b|modal|docker) ;; *) fail "HARBOR_ENV must be e2b, modal or docker" ;; esac
case "$part" in both|e2b|modal) ;; *) fail "PART must be both, e2b or modal" ;; esac
harness=${HARNESS:-}
run=${RUN:-${model##*/}-$effort}
root=$(cd -- "$(dirname -- "$0")" && pwd)

uses_modal() {
  [ "$environment" = modal ] && return 0
  [ "$environment" = e2b ] && [ "$part" != e2b ] || return 1
  for bench in $benchmarks; do [ -f "$root/$bench/modal-tasks.txt" ] && return 0; done
  return 1
}
command -v harbor >/dev/null || fail 'Install Harbor first: uv tool install "harbor[e2b,modal]==0.22.0" --with "reason-machines-harbor>=0.3.19"'
: "${REASON_API_KEY:?Set REASON_API_KEY (see README.md)}"
case " $benchmarks " in
  *" swe-atlas-qna "*) : "${ANTHROPIC_API_KEY:?SWE-Atlas QnA grading needs ANTHROPIC_API_KEY (see README.md)}" ;;
esac
[ "$environment" != e2b ] || [ "$part" = modal ] || : "${E2B_API_KEY:?Set E2B_API_KEY, or use HARBOR_ENV=docker (see README.md)}"
if uses_modal; then
  command -v uv >/dev/null || fail "Install uv first (see README.md)"
  [ -n "${MODAL_TOKEN_ID:-}" ] || [ -f "$HOME/.modal.toml" ] \
    || fail "Log in to Modal (modal token new) or set MODAL_TOKEN_ID and MODAL_TOKEN_SECRET (see README.md)"
fi

# A Modal sandbox may live for the task's agent, setup and grading budgets plus 30 minutes.
lifetime() {
  case "$1" in deepswe) echo 10800 ;; swe-atlas-qna) echo 15300 ;; terminal-bench) echo 34200 ;; esac
}

harbor_run() {
  local bench=$1 part=$2 env=$3 harbor_env concurrency task
  shift 3
  case "$env" in
    # e2b drops the image's ENV; the adapter's environment (0.3.16+) passes it to the sandbox, PATH included.
    e2b) harbor_env=reasonmachines_harbor.environment:ReasonE2BEnvironment concurrency=${E2B_CONCURRENCY:-10} ;;
    modal) harbor_env=modal concurrency=${MODAL_CONCURRENCY:-8} ;;
    docker) harbor_env=reasonmachines_harbor.environment:ReasonDockerEnvironment concurrency=${DOCKER_CONCURRENCY:-2} ;;
  esac
  local args=(
    --dataset "$(dataset "$bench")"
    --agent reasonmachines_harbor:ReasonAgent
    --model "$model"
    --ak "reasoning_effort=$effort"
    --ak mode=ephemeral
    --allow-agent-host api.reasonmachines.com
    --allow-agent-host relay.reasonmachines.com
    --env "$harbor_env"
    --n-attempts "${ATTEMPTS:-3}" --n-concurrent "$concurrency"
    # Infrastructure errors are retried; timeouts are results.
    --max-retries 3 --retry-exclude AgentTimeoutError --retry-exclude VerifierTimeoutError
    --enable-verification -y
    --jobs-dir "$root/jobs/$run/$bench/$part" --job-name "$(date -u +%Y%m%dT%H%M%SZ)"
  )
  [ -z "$harness" ] || args+=(--ak "runtime_profile=$harness")
  if [ "$bench" = swe-atlas-qna ]; then
    # The grader is Claude Opus 4.5 through Anthropic's OpenAI-compatible API.
    args+=(--ve 'EVAL_API_KEY=${ANTHROPIC_API_KEY}' --ve EVAL_BASE_URL=https://api.anthropic.com/v1/
      --ve EVAL_MODEL=claude-opus-4-5-20251101)
    # SWE-Atlas images set ENTRYPOINT ["/bin/bash"], so Harbor's keep-alive has to be bash
    # arguments on Modal; on Docker an overlay replaces the entrypoint.
    case "$env" in
      modal) args+=(--ek 'keepalive=["-c","sleep infinity"]') ;;
      docker) args+=(--extra-docker-compose "$root/swe-atlas-qna/keepalive.compose.yaml") ;;
    esac
    # e2b stops at 8 CPUs / 8 GiB and SWE-Atlas tasks ask for 16 / 16; every cloud trial runs
    # at 8 / 8 so the e2b and Modal halves match.
    [ "$env" = docker ] || args+=(--override-cpus 8 --override-memory-mb 8192)
  fi
  # Part e2b skips the benchmark's modal-tasks.txt; part modal runs only those tasks.
  # Your own -i selects tasks instead of the whole Modal list (Harbor unions -i).
  local selected=""
  case " ${extra[*]-} " in *" -i "*|*" --include-task-name "*) selected=1 ;; esac
  if [ "$part" != all ] && [ -f "$root/$bench/modal-tasks.txt" ]; then
    while read -r task; do
      case "$task" in ''|'#'*) continue ;; esac
      if [ "$part" = e2b ]; then args+=(-x "$task"); elif [ -z "$selected" ]; then args+=(-i "$task"); fi
    done < "$root/$bench/modal-tasks.txt"
  fi
  DOCKER_DEFAULT_PLATFORM=linux/amd64 harbor run "${args[@]}" "$@" ${extra[@]+"${extra[@]}"}
}

# Every Modal job runs in its own app with a hard sandbox lifetime. A watcher stops the app
# when Harbor exits for any reason, and the job ends only once nothing is left running.
apps="$root/logs/$run-$(date -u +%Y%m%dT%H%M%SZ).modal-apps"
guard() { uv run -q "$root/modal_guard.py" "$@"; }
modal_job() {
  local bench=$1 part=$2 app pid status
  app="reason-bench-$(date -u +%Y%m%d%H%M%S)-$bench"
  echo "$app" >> "$apps"
  guard fresh "$app"
  harbor_run "$bench" "$part" modal --ek "app_name=$app" --ek "sandbox_timeout_secs=$(lifetime "$bench")" &
  pid=$!
  guard watch "$pid" "$app" > "$root/logs/$app.guard.log" 2>&1 &
  status=0
  wait "$pid" || status=$?
  guard stop "$app" || status=1
  return "$status"
}
stop_modal() {
  [ -f "$apps" ] || return 0
  while read -r app; do guard stop "$app" || true; done < "$apps"
}
trap 'stop_modal; kill 0' INT TERM

mkdir -p "$root/logs"
status=0
if [ "$environment" = e2b ]; then
  printf 'Run %s: e2b part -> logs/%s-e2b.log, Modal part -> logs/%s-modal.log\n' "$run" "$run" "$run"
  (
    [ "$part" != modal ] || exit 0
    half=0
    for bench in $benchmarks; do harbor_run "$bench" e2b e2b || half=1; done
    exit "$half"
  ) > "$root/logs/$run-e2b.log" 2>&1 &
  e2b_half=$!
  (
    [ "$part" != e2b ] || exit 0
    half=0
    for bench in $benchmarks; do
      [ -f "$root/$bench/modal-tasks.txt" ] || continue
      modal_job "$bench" modal || half=1
    done
    exit "$half"
  ) > "$root/logs/$run-modal.log" 2>&1 &
  modal_half=$!
  wait "$e2b_half" || status=1
  wait "$modal_half" || status=1
else
  for bench in $benchmarks; do
    if [ "$environment" = modal ]; then modal_job "$bench" all || status=1
    else harbor_run "$bench" all docker || status=1
    fi
  done
fi
stop_modal
# Screen for reward hacking before scoring. SCREEN_JUDGE=1 also runs the paid judge (screening/screen.py).
judge=(); [ "${SCREEN_JUDGE:-0}" != 1 ] || judge=(--judge)
python3 "$root/screening/screen.py" ${judge[@]+"${judge[@]}"} "$root/jobs/$run" || true
python3 "$root/score.py" "$root/jobs/$run" || true
exit "$status"
