# Guide

How to run this repository, what each part does, and why it works the way it
does. The [README](../README.md) is the short version; the
[methodology](METHODOLOGY.md) has the scoring rules.

## How a run works

```
you ── run.sh ──> Harbor ──> task container (e2b, Modal or Docker)
                                 │  the adapter installs the Reason CLI and starts a worker
                                 ▼
                     Reason API ──> a Session in a new, empty workspace
                                 │  the model works in the container through the worker
                                 ▼
                     the task's own verifier grades the container ──> reward
                                 ▼
          screening/screen.py (reward hacking) ──> score.py (pass@1, cost, builds)
```

- **Harbor** starts each task's container, runs the agent, then runs the
  task's own tests or grader. We never grade anything ourselves.
- **The adapter** (`reason-machines-harbor` on PyPI) is the Harbor agent. It
  installs a pinned, checksummed Reason CLI in the container and starts it as
  a worker. Your API key stays on your machine; the container only gets a
  one-use enrollment ticket.
- **Reason** runs the attempt as a normal Session, in a new single-use
  workspace, on a frozen harness release.
- **`score.py`** reads Harbor's job folders and turns them into scores, costs
  and a list of what every attempt ran on.

## Step by step

### 1. Accounts and keys

| You need | For | Where |
|---|---|---|
| [uv](https://docs.astral.sh/uv/getting-started/installation/) and Docker | everything | |
| Reason API key | every run | [Customize › API](https://reasonmachines.ai/customize?tab=api), owner or admin, scopes `run`, `sessions:read`, `deployment:read`, `devices:read`, `devices:write`, `devices:use`, `org:write` |
| Paid model access, or your own provider key | the model | [Customize › Models](https://reasonmachines.ai/customize?tab=models); with your own key use `byok:<provider>:<model>` |
| Anthropic API key | grading SWE-Atlas QnA (Claude Opus 4.5) | console.anthropic.com |
| e2b API key | the default cloud sandboxes | e2b.dev |
| Modal login | tasks e2b can't host (GPUs, many containers) | `uvx modal token new` |

Local Docker needs only the first three rows, plus the Anthropic key for SWE-Atlas QnA.

### 2. Install

```bash
uv tool install "harbor[e2b,modal]==0.22.0" --with "reason-machines-harbor>=0.3.44"
git clone https://github.com/reason-machines/benchmark && cd benchmark
export REASON_API_KEY=...        # and ANTHROPIC_API_KEY, E2B_API_KEY as needed
```

### 3. Check your setup on one task

```bash
harbor run --dataset datacurve/deep-swe-1-1 --n-tasks 1 \
  --agent reasonmachines_harbor:ReasonAgent --model openai/gpt-6-luna \
  --ak reasoning_effort=low \
  --allow-agent-host api.reasonmachines.com --allow-agent-host relay.reasonmachines.com
```

It should end with a reward table. `jobs/<time>/<task>/agent/session.json`
links to the Session.

### 4. Run a benchmark

```bash
./run.sh deepswe                          # e2b, plus Modal for the tasks e2b can't host
HARBOR_ENV=docker ./run.sh deepswe        # all on local Docker
PART=e2b ./run.sh swe-atlas-qna -l 5      # 5 tasks, e2b only, no Modal
MODEL=byok:openai:gpt-6-luna EFFORT=high ./run.sh terminal-bench
```

Each benchmark runs three attempts per task (`ATTEMPTS`). Results go to
`jobs/<model>-<effort>/<benchmark>/<part>/<job>/`, logs to `logs/`. The
README lists every setting.

### 5. A full, publishable pass

```bash
./run-pass.sh oracle      # every task's reference solution: every task must score 1
./run-pass.sh nop         # no work: every task must score 0
./run-pass.sh openai/gpt-6-luna xhigh
```

The preflight shows each environment grades a task the way its authors do.
The pass runs all three benchmarks, writes a manifest of what ran to `logs/`,
then screens and scores with `--strict`.

### 6. Score, rerun, score again

```bash
uv run screening/screen.py jobs/<run>          # flags suspicious steps; --judge adds the paid judge
uv run score.py jobs/<run>                     # the table
uv run score.py --strict jobs/<run>            # is it complete, on one configuration?
```

`score.py` lists tasks with empty attempt slots (infrastructure errors).
Rerun just those with `./run.sh <benchmark> -i <task> ...` into the same run
folder; a rerun fills an empty slot and never replaces a result. Score again.

### 7. Publish

```bash
harbor upload jobs/<run>/<benchmark>/<part>/<job>
```

Publish the run's manifest, score, screening and `adjudications.json` with
it. Harbor Hub shows each attempt's `cost_usd`, which is what Reason charged
(see [Cost](#cost)), not the list-price cost in `score.py`'s table.

## What each file does

| File | Does |
|---|---|
| `run.sh` | One benchmark or all three: checks keys, pins each dataset by registry digest, splits tasks between e2b and Modal, starts Harbor, then screens and scores |
| `run-pass.sh` | A whole pass or its oracle/nop preflight, with fixed concurrency and a manifest |
| `<benchmark>/modal-tasks.txt` | Tasks e2b can't host, and why |
| `modal_guard.py` | Gives each Modal job its own app with a hard lifetime and stops it when Harbor exits, so no GPU is left running |
| `screening/` | The reward-hacking scan and Artificial Analysis's judge rubric |
| `score.py` | Attempt slots, pass@1, confidence intervals, builds, trajectory checks and cost |
| `tests/` | `uv run --python 3.12 python -m unittest discover tests` |

## Decisions and why

- **A frozen harness release.** Reason's default harness changes with every
  deploy; a dated release (`runtime/reason-agent-1.3`, the adapter's default)
  never changes, so a rerun months later runs the same prompt and tools.
  `score.py --strict` checks every attempt reports one harness digest.
- **A new, empty workspace per attempt.** Nothing carries over between
  attempts: no memory, skills or files from earlier tasks.
- **Datasets pinned by digest.** Every run gets exactly the same tasks.
- **e2b first, Modal for the rest.** e2b is cheap and fast to start; tasks it
  can't host (GPUs, several containers, more than 8 CPUs / 8 GiB) run on
  Modal. SWE-Atlas runs at 8 CPUs / 8 GiB on e2b and Modal so both halves match.
- **Harbor 0.22.0 in the scripts.** Our published results ran on it. The
  adapter also works with Harbor up to 0.25 for your own runs.
- **Attempt slots.** Reruns fill empty slots in the order attempts ran and
  never replace a result, so rerunning can't be used to pick good results.
  Timeouts score 0; infrastructure errors don't count and get rerun.
- **Provider refusals are redrawn** up to 10 times, as Artificial Analysis
  does.
- **Reward-hacking screening.** A Terminal-Bench pass the judge fails scores
  0, as Artificial Analysis scores it.
- **Cost from tokens, at list prices.** Comparable with any other agent and
  recomputable from the trajectory alone.
- **Checks before launch.** The scripts refuse to start without the keys a
  benchmark needs, and test the SWE-Atlas grader key, because a bad key
  otherwise turns every attempt into a grading timeout scored 0.
- **The scripts run as one function,** so pulling or editing the repository
  during an hours-long run can't change what the run executes.

## Cost

Two numbers, both correct, for different questions:

| | What it is | Where |
|---|---|---|
| **List-price cost** | The tokens priced at the provider's published rates: what the model calls cost | `score.py`'s table |
| **Reason charged** | The Session's `cost_usd`: list price plus 25% when Reason pays for the model; exactly list price with your own key (`byok:`), which your provider bills directly | `cost_usd` in Harbor's results and on Harbor Hub; "Reason charged" in `score.py` |

How we checked the tokens and cost are real (November 2, 2026):

1. The trajectory's per-response tokens add up to the Session's totals, to
   Harbor's `agent_result` and to the Reason API's Session usage: identical
   on every attempt.
2. Each attempt's model calls in the trajectory are exactly the calls Reason's
   inference gateway served for it, and `score.py`'s cost equals the
   gateway's provider cost.
3. For a whole day of gpt-6-luna traffic, the gateway's tokens match OpenAI's
   usage API to within 0.5% and its cost matches OpenAI's cost API to within
   0.6%. `PRICES` matches OpenAI's published price page.
4. With your own key (`byok:openai:gpt-6-luna`, one task per benchmark, subagents
   included), every call and token matches OpenAI's usage API minute by minute.
5. The first request's prompt tokens match the exported system prompt, tool
   definitions and task: nothing the model was sent is missing from the
   trajectory.

Not in the agent cost: the SWE-Atlas grader and the reward-hacking judge,
which bill your Anthropic key, and sandbox time on e2b or Modal.

## Trajectories

`agent/trajectory.json` in each attempt is ATIF: the system prompt, tool
definitions, every model response with its reasoning summary and token
counts, every tool call and its full output, and `extra.fidelity`, which
counts anything masked. `score.py --strict` fails an attempt whose trajectory
was cut or masked beyond injected secrets and Reason-issued tokens.
