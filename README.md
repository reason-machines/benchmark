# Reason on the Coding Agent Index

Run [Reason](https://reasonmachines.ai) with [Harbor](https://harborframework.com)
on the three benchmarks of the
[Artificial Analysis Coding Agent Index](https://artificialanalysis.ai/agents/coding-agents) (v1.5).

| Benchmark | Harbor dataset | Tasks |
|---|---|---|
| [DeepSWE v1.1](deepswe/) | [`datacurve/deep-swe-1-1`](https://hub.harborframework.com/datasets/datacurve/deep-swe-1-1/latest) | 113 |
| [SWE-Atlas QnA](swe-atlas-qna/) | [`scale-ai/swe-atlas-qna`](https://hub.harborframework.com/datasets/scale-ai/swe-atlas-qna/latest) | 124 |
| [Terminal-Bench 4.0](terminal-bench/) | [`terminal-bench/terminal-bench@4`](https://hub.harborframework.com/datasets/terminal-bench/terminal-bench/4) | 66 |

Harbor starts each task's container and grades it with the task's own verifier.
Reason works on that container as a normal Session, in a new, empty workspace
for every attempt. We recommend running a pinned harness release, which never
changes, so every rerun runs the same harness. The adapter (0.3.43 or later)
requests `runtime/reason-agent-1.3` by default, so the commands below run it without naming it;
to rerun an earlier release, name it, for example `--ak runtime_profile=runtime/reason-agent-1.2`.
Results here are on the Artificial Analysis Coding Agent Index v1.5.
Each benchmark scores pass@1, averaged over three attempts per task, and the
Index is the equal-weight mean of the three. Timeouts score 0, provider refusals are redrawn
up to 10 times, and a Terminal-Bench attempt the reward-hacking judge fails
scores 0. See the [methodology](docs/METHODOLOGY.md) for the full rules and
their version history.

## Quick start

You need [uv](https://docs.astral.sh/uv/getting-started/installation/), Docker
and a [Reason API key](https://reasonmachines.ai/customize?tab=api) with `run`,
`sessions:read`, `deployment:read`, `devices:read`, `devices:write`,
`devices:use` and `org:write`, from an owner or admin of a workspace with paid
model access. Enable the model under
[Models](https://reasonmachines.ai/customize?tab=models).

```bash
uv tool install "harbor[e2b,modal]==0.22.0" --with "reason-machines-harbor>=0.3.43"
export REASON_API_KEY=<YOUR-REASON-KEY>

# One DeepSWE task on local Docker, to check your setup.
# For your own provider key, connect it under Models and use --model byok:openai:gpt-6-luna
harbor run --dataset datacurve/deep-swe-1-1 --n-tasks 1 \
   --agent reasonmachines_harbor:ReasonAgent \
   --model openai/gpt-6-luna \
   --ak reasoning_effort=xhigh \
   --allow-agent-host api.reasonmachines.com \
   --allow-agent-host relay.reasonmachines.com
```

Drop `--n-tasks 1` to run every task once. The worker connects out to the
Reason API and relay, so both `--allow-agent-host` flags are needed even on
offline tasks. Each trial's folder under `jobs/` holds the Session's
trajectory (`agent/trajectory.json`), its link and cost (`agent/session.json`)
and the verifier's result.

## Full runs

[`run.sh`](run.sh) runs one benchmark or all three with the pinned task sets,
three attempts per task, then screens and scores the run.
[`run-pass.sh`](run-pass.sh) runs a whole publishable pass and its
preflight (see the [methodology](docs/METHODOLOGY.md#before-and-after-a-pass)).

```bash
./run.sh deepswe                         # e2b, with the tasks e2b can't host on Modal
HARBOR_ENV=docker ./run.sh deepswe       # everything on local Docker, no cloud accounts
./run-pass.sh openai/gpt-6-luna xhigh    # all three benchmarks, e2b + Modal
```

| Variable | Needed for | |
|---|---|---|
| `REASON_API_KEY` | every run | See quick start |
| `ANTHROPIC_API_KEY` | SWE-Atlas QnA grading; `SCREEN_JUDGE=1` | The grader is Claude Opus 4.5; the agent never sees this key |
| `E2B_API_KEY` | `HARBOR_ENV=e2b` (the default) and `run-pass.sh` | From [e2b](https://e2b.dev/dashboard) |
| Modal login | the Modal half and `run-pass.sh` | `uvx modal token new`, or `MODAL_TOKEN_ID` and `MODAL_TOKEN_SECRET`; `MODAL_PROFILE` picks the workspace |

`run.sh` settings, all optional:

| Variable | Default | Meaning |
|---|---|---|
| `MODEL` | `openai/gpt-6-luna` | Model id, or `byok:<provider>:<model>` |
| `EFFORT` | `xhigh` | `minimal`, `low`, `medium`, `high`, `xhigh` or `max` |
| `HARBOR_ENV` | `e2b` | `e2b` (with Modal for the tasks in `<benchmark>/modal-tasks.txt`), `modal` or `docker` |
| `PART` | `both` | With e2b: `e2b` skips the Modal tasks, `modal` runs only them |
| `ATTEMPTS` | `3` | Attempts per task (`run-pass.sh` reads it too) |
| `HARNESS` | the adapter's default release | A runtime profile, for example `runtime/reason-agent-1.2` (`run-pass.sh` reads it too) |
| `RUN` | `<model>-<effort>` | Folder under `jobs/` |
| `E2B_CONCURRENCY`, `MODAL_CONCURRENCY`, `DOCKER_CONCURRENCY` | `10`, `8`, `2` | Trials at a time |
| `SCREEN_JUDGE` | `0` | `1` also runs the paid reward-hacking judge |

Extra arguments after the benchmark go to `harbor run`, for example
`./run.sh deepswe -i datacurve/igel-persist-feature-schema` or `-l 5`.

## Scoring

Results land in `jobs/<run>/<benchmark>/<part>/<job>/`. Both scripts score
the run when they finish; to rescore, or to score a run you completed with
reruns:

```bash
uv run screening/screen.py jobs/<run>   # reward-hacking scan
uv run score.py jobs/<run>              # pass@1, intervals, builds and cost
uv run score.py --strict jobs/<run>     # also check the run is complete on one configuration
```

`score.py` prices each model response from its `PRICES` table. A model not in
the table falls back to the cost Reason reported; add its list prices there to
price it from the trajectory.

## Troubleshooting

- `missing_scope`, `forbidden`: the key lacks a scope listed above, or isn't
  an owner or admin key.
- `ephemeral_workspace_parent_payment_required`: the workspace has no paid
  model access. Add billing, or bring your own provider key with `byok:`.
- `execution_ineligible` at worker startup: upgrade the adapter to 0.3.43 or
  later.
- "the worker needs Reason egress on this offline task": add both
  `--allow-agent-host` flags.
- Problems with the adapter or these scripts:
  [open an issue](https://github.com/reason-machines/benchmark/issues).

## Citation

```bibtex
@misc{reasonmachines2026benchmark,
  title        = {Reason on the Coding Agent Index},
  author       = {{Reason Machines}},
  year         = {2026},
  howpublished = {\url{https://github.com/reason-machines/benchmark}}
}
```
