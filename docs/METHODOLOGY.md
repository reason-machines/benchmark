# Methodology

Version 1.6.1. How we run and score Reason on the three benchmarks of the
[Artificial Analysis Coding Agent Index](https://artificialanalysis.ai/agents/coding-agents)
v1.5, which this version is based on.

## Benchmarks

| Benchmark | Tasks | Harbor dataset (pinned in [`run.sh`](../run.sh)) | An attempt passes when |
|---|---|---|---|
| DeepSWE v1.1 | 113 | `datacurve/deep-swe-1-1` | every hidden test passes |
| SWE-Atlas Codebase QnA | 124 | `scale-ai/swe-atlas-qna` | every rubric item passes (Scale's Task Resolve Rate), judged by Claude Opus 4.5 |
| Terminal-Bench 4.0 | 66 | `terminal-bench/terminal-bench@4` | the task's test suite passes |

Each dataset is pinned by registry digest, so every pass runs the same task set.
Each task's own verifier grades it through [Harbor](https://harborframework.com).

## Scoring

- **pass@1:** average each task's attempt scores, then average across tasks, so
  each task has equal weight. A standard pass runs three attempts per task; a
  run's notes state the count it used.
- **Attempt slots:** each task has one slot per attempt. Its attempts are taken
  in the order they ran, across every job and environment of the run, and each
  result fills the next empty slot. A rerun fills an empty slot and never
  replaces a result. A slot still empty scores 0.
- **Index:** the equal-weight mean of the three benchmark pass@1 scores.
- **Confidence interval:** 95%, from 2,000 bootstrap resamples of the tasks.
  The Index's interval resamples every benchmark's tasks together.
- **Attempt spread:** with more than one attempt per task, the lowest and
  highest pass@1 of a single attempt slot (every task's first attempt, every
  task's second, and so on): how much one run of the benchmark varies.
- **Rows:** each model at one reasoning effort is its own row.

[`score.py`](../score.py) computes all of these from Harbor's job folders.

## Attempts that don't finish

- An attempt that runs past its agent or grading time limit scores 0, even if
  its verifier still graded it.
- An attempt that Reason refuses (`instruction_blocked`) on every try scores 0.
- **Provider refusals** are redrawn, as Artificial Analysis does: when the model
  provider refuses the request, the attempt is run again, up to 10 times. A
  slot whose first draw and all 10 redraws are refused scores 0.
- Infrastructure errors are retried up to 3 times. A slot still without a
  result is run again later, and its first result counts. DeepSWE's
  grader-crash reward (-1) counts as no result.
- **Harness and environment bugs:** an attempt that ran under a confirmed bug in
  Reason, the adapter or the task environment is void, whatever its result.
  Every attempt the bug could have affected is voided, chosen by the bug's
  cause, not by the attempt's score. Each is replaced by a rerun on the fixed
  build, and the run's notes name the bug, the fix and the attempts
  replaced.

`score.py` reads these decisions from the trial files, and from
`adjudications.json` in the run folder for void attempts and for refusals
Reason did not classify.

## Before and after a pass

- **Preflight:** before each pass, `./run-pass.sh oracle` and
  `./run-pass.sh nop` run Harbor's oracle agent (each task's reference
  solution) and nop agent (no work) on the same environments. Every task must
  score 1 under oracle and 0 under nop (`score.py --expect`). A task that
  doesn't is fixed or moved to another environment before the pass, and the
  run's notes say so. This shows each environment grades a task as its
  authors do; an environment that loses the image's PATH fails it.
- **Builds:** `score.py` lists what the counted attempts ran on: model,
  reasoning effort, adapter version, Reason runtime profile, harness digest
  and features, environment, Reason server commit and worker version. Reason deploys
  continuously, so server and worker builds vary within a pass; the run's
  notes list them. The others must be the same for every counted attempt.
- **Publishing:** a pass is published only when `score.py --strict` passes:
  every task of every benchmark has all its attempt slots filled, on one
  configuration, and every counted attempt passes the trajectory gates below.
  Its manifest, score, screening and adjudications are published with its
  public Harbor job.

## Agent

- **Harness:** Reason, through the [Reason Harbor adapter](https://github.com/reason-machines/reason-machines-harbor)
  (0.3.19 or later). The agent works on the task container as a normal Reason
  Session on a dated harness release, `runtime/reason-v7-2026-10` unless a
  run's notes name another: Reason's default harness as it ran in October
  2026, frozen. Reason keeps changing its default harness; a release never
  changes, and a change ships as a new dated release. The adapter requests the
  current release by default in ephemeral mode, and any Reason workspace can
  request one by name (`--ak runtime_profile=...`). `score.py` lists the runtime profile
  each counted attempt reports, and `--strict` requires a single one.
- **State:** every attempt starts in a new, empty, single-use workspace.
  Memory and skills are on, as in any workspace, but the workspace starts
  with none, so nothing carries over between attempts.
- **Time:** each Session gets the task's own agent time limit plus 10 minutes,
  up to 12 hours.
- **Network:** each task's own policy. DeepSWE runs without internet, except
  the Reason API and relay hosts the worker needs, and without Reason's
  cloud-side web tools. Terminal-Bench and SWE-Atlas QnA have internet.

## Reward hacking

[`screening/screen.py`](../screening/screen.py) scans every attempt and lists
suspicious steps for review. With `SCREEN_JUDGE=1`, each passing Terminal-Bench
attempt also goes to Artificial Analysis's judge: `harbor analyze` with Claude
Sonnet 5 and [their criterion](../screening/rubric.toml). An attempt it fails
scores 0.

## Trajectories

Each attempt's `agent/trajectory.json` (ATIF) is the Session as the model saw it.

- It includes the system prompt, the tool definitions the model was offered,
  and, at each context compaction, the summary the model continued from.
- Tool output is exported whole. Only the literal secret values we inject,
  shown as `[redacted-secret]`, and the shapes of tokens Reason issues are
  masked. Task content that looks like a credential stays.
- OpenAI encrypts model reasoning, so trajectories hold its reasoning
  summaries only.
- `extra.fidelity` counts redactions by marker as they are applied, and tool
  results that fell back to a 4k excerpt. Each agent step names the Reason
  server commit that served it.

`score.py --strict` requires, for every counted attempt, a trajectory with no
excerpts and no redaction other than injected secrets and Reason-issued tokens
(fidelity), and one
server commit for all its agent steps (one build). It lists the harness digest
each attempt reports and requires a single one. An attempt whose trajectory
doesn't record these fails the gate.

## Environment

- Tasks run on [e2b](https://e2b.dev), through the adapter's
  `ReasonE2BEnvironment` (reason-machines-harbor 0.3.16 or later), which gives
  the task container its image's environment variables, PATH included, as
  Docker would. Tasks
  e2b can't host, listed in each benchmark's `modal-tasks.txt`, run on
  [Modal](https://modal.com).
- Tasks on a benchmark's `modal-tasks.txt` can instead run in a `lambda` part:
  plain Docker on remote hosts (Lambda Cloud H100 SXM/PCIe and A10; GCP
  a3-highgpu-1g H100 SXM, flex-start), through Harbor's ec2 environment
  attached to the host, one GPU per GPU trial. Its jobs go under
  `jobs/<run>/<benchmark>/lambda/` and are scored with the other parts; a
  run's notes name each trial's host type. The environment class is not in
  this repository yet; a run that used it says so in its notes.
- Each task gets the CPUs and memory it asks for, except SWE-Atlas QnA, which
  runs at 8 CPUs / 8 GiB instead of 16 / 16 (e2b's limit), on both e2b and Modal.

## Cost

Cost per attempt is priced from the attempt's trajectory, so anyone can
recompute it. Each model response records the tokens the provider reported.
`score.py` prices every response from its committed price table (`PRICES`),
including the responses of any subagents the attempt started:

- uncached input, cache reads, cache writes and output are priced separately;
- a request with more than 272k input tokens uses the long-context rates;
- the responses must add up to the token totals the Session recorded.

When an attempt's trajectory lacks that usage, for example an export recorded
before per-response usage existed, the cost Reason reported for the attempt is
used instead. The table says how many attempts used it, and `--strict`
requires every attempt to be priced. Below the table, the cost of each token
kind is listed. Attempts without any cost are left out of the average, and the
table shows how many had one. Agent time is the median time the agent ran per
counted attempt. With your own provider key (`byok:<provider>:<model>`), your
provider bills the model calls directly.

Reason's server reported only a trial's own Session until October 9, 2026, so
earlier Harbor results under-count attempts that started subagents. Repricing
from the trajectory doesn't fix those, because their exports don't include the
subagents either.

## Version history

| Version | Date | Changes |
|---|---|---|
| 1.0 | October 2026 | First version, based on the Artificial Analysis Coding Agent Index v1.5. |
| 1.1 | October 2026 | Reward-hacking screening; DeepSWE without cloud-side web tools. |
| 1.2 | October 2026 | Attempt slots across jobs; timeouts score 0 even when graded; provider-refusal redraws; void attempts from confirmed harness or environment bugs; e2b keeps the image's environment variables; Lambda GPU part. |
| 1.2.1 | October 2026 | e2b requires adapter 0.3.16: e2b's login shell reset PATH and dropped the image's PATH entries, which 0.3.15 still lost. Lambda GPU hosts may be H100 SXM or PCIe. |
| 1.3 | October 2026 | Oracle and nop preflight before each pass; builds of the counted attempts are listed, and a pass is published only when complete on one configuration (`score.py --strict`); Index interval; attempt spread; cost coverage and agent time. |
| 1.4 | October 2026 | Every pass runs a dated, frozen harness release, `runtime/reason-v7-2026-10` by default (adapter 0.3.18 or later). |
| 1.4.1 | October 2026 | The adapter (0.3.19 or later) requests the dated release by default, so commands no longer name it. |
| 1.5 | October 2026 | Trajectories: masking policy, system prompt, tool definitions and compaction summaries included, reasoning summaries only; `--strict` adds the fidelity, one-build and single harness digest gates. Screening reads the server's redaction counts. |
| 1.5.1 | October 2026 | The `lambda` part is any remote plain-Docker host (Lambda Cloud H100 SXM/PCIe and A10, GCP a3-highgpu-1g H100), for any task on a `modal-tasks.txt` list. |
| 1.6 | October 2026 | Cost is priced per model response from the trajectory's token counts and a committed price table, subagents included, with the cost of each token kind listed; `--strict` requires complete token usage. |
| 1.6.1 | October 2026 | Results are published as public Harbor Hub jobs, each with its notes (builds, voids, reruns, refusals, judge results), manifest, score and screening; this repository holds the runner, scorer and methodology. |

## References

```bibtex
@software{Harbor_Framework,
  author = {{Harbor Framework Team}},
  title  = {{Harbor: A framework for evaluating and optimizing agents and models in container environments}},
  year   = {2026},
  doi    = {10.5281/zenodo.20953922},
  url    = {https://doi.org/10.5281/zenodo.20953922}
}

@misc{artificialanalysis2026codingagentindex,
  title        = {Coding Agent Index v1.5 Methodology},
  author       = {{Artificial Analysis}},
  year         = {2026},
  howpublished = {\url{https://artificialanalysis.ai/methodology/coding-agents-benchmarking}},
  note         = {Accessed 2026-10-03}
}
```
