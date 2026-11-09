# Methodology

Version 1.10.3. How we run and score Reason on the three benchmarks of the
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
- **Agent-side endings:** an attempt whose Reason Session ends on the agent's
  own side without a result (for example `error_class` `stuck` or
  `agent_ended_without_text`), with no evidence of an infrastructure cause, is
  a counted attempt that scores 0, not an infrastructure error. The run's
  `adjudications.json` lists each under `"scored_zero"` with its reason;
  `score.py` fills the attempt's slot with 0 and lists it below the table.
  A graded, timed-out, blocked or refused attempt is scored by its own rule,
  and a void attempt stays void.
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
`adjudications.json` in the run folder for void attempts, for refusals
Reason did not classify, and for agent-side endings scored 0 (`"void"`,
`"refused"` and `"scored_zero"`, each keyed by trial or job folder for
`"void"`, by trial folder for the others). Every key is optional; a file
without `"scored_zero"` scores as before.

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
- **Strict check:** `score.py --strict` passes when every task of every
  benchmark has all its attempt slots filled, on one configuration, and every
  counted attempt passes the trajectory gates below. We recommend it for every
  pass. Our October 2026 Hub jobs predate some of its gates (pinned harness,
  per-response token usage, trajectory fidelity) and don't pass them. A pass's
  manifest, score, screening and adjudications are published with its public
  Harbor job.

## Agent

- **Harness:** Reason, through the [Reason Harbor adapter](https://github.com/reason-machines/reason-machines-harbor)
  (0.3.43 or later). The agent works on the task container as a normal Reason
  Session. We recommend a dated harness release: Reason keeps changing its
  default harness; a release never changes, and a change ships as a new dated
  release. Runs before the releases existed used the default harness of the
  time, and their trials name it. Any Reason workspace can request a release by
  name (`--ak runtime_profile=...`); the adapter (0.3.43 or later) requests
  `runtime/reason-agent-1.3` by default in ephemeral mode. To rerun an earlier
  release, name it, for example `runtime/reason-agent-1.2`. `score.py` lists
  the runtime profile each counted attempt reports, and `--strict` requires a
  single one.
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
- Tools carry the names the model saw. Dated releases from v8 call the
  JavaScript tool `reason`; exports recorded before November 2, 2026 name it
  `codemode`, Reason's internal name.
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
(fidelity). It lists the harness digest each attempt reports and requires a
single one. An attempt whose trajectory doesn't record these fails the gate.
It also lists how many attempts ran on more than one server commit, because
Reason deployed during them, but doesn't gate on it: the harness digest fixes
the prompt and tools the model is given, and production deploys many times
during a pass.

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
- OpenAI cache writes use its 30-minute write rate; Anthropic cache writes use
  its 5-minute rate (1.25x input), except a step's one-hour writes
  (`extra.cache_write_1h_tokens`, which `runtime/reason-agent-1.3` makes on
  direct Anthropic requests), priced at 2x input;
- a request with more than 272k input tokens uses the long-context rates;
- the responses must add up to the token totals the Session recorded.

**Two costs.** The table's cost is the provider's list price for the tokens:
what the model calls cost, comparable with other agents. When Reason pays for
the model (a model id without `byok:`), Reason charges list price plus 25%.
That charge is the `cost_usd` Harbor records for the attempt and uploads to
Harbor Hub, and `score.py` lists it below the table as "Reason charged". With
your own provider key, your provider bills the model calls and `cost_usd` equals
the list-price cost.

**How we checked it** (November 2, 2026, `openai/gpt-6-luna`): for every
attempt, the trajectory's per-response tokens add up to the Session's totals,
Harbor's `agent_result` and the Reason API's Session usage; each attempt's
model calls in the trajectory are exactly the calls Reason's inference
gateway served for it; `score.py`'s cost equals the gateway's provider cost,
and Reason's charge is 1.25 times it. For a whole day, the gateway's
gpt-6-luna tokens match OpenAI's usage API to within 0.5% (OpenAI also bills
about 0.4% more requests: streams cut off before they finished) and its cost
matches OpenAI's cost API to within 0.6%. `PRICES` matches OpenAI's
published prices.

When an attempt's trajectory lacks that usage, for example an export recorded
before per-response usage existed, the cost Reason charged for the attempt is
used instead (list price plus 25% on Reason-paid models, so those attempts read
high). The table says how many attempts used it, and `--strict`
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
| 1.6.2 | October 2026 | The pinned harness release and `--strict` are recommended, not claimed for every published pass: the October 2026 results ran on the default harness of the time and predate some `--strict` gates. |
| 1.6.3 | October 2026 | `--strict` lists attempts that ran across a Reason deploy instead of failing them; the single harness digest is what it gates. |
| 1.7 | October 2026 | Recommended release `runtime/reason-v8.1-2026-10` (adapter 0.3.35 or later); the adapter default stays `runtime/reason-v7-2026-10`. |
| 1.8 | October 2026 | The adapter (0.3.38 or later) requests `runtime/reason-agent-1.2` by default; earlier releases are named explicitly. Claude Opus 5.5 joins the price table. Based on Coding Agent Index v1.5; Artificial Analysis moved to v2.0 on October 22, 2026. |
| 1.8.1 | October 2026 | Adapter 0.3.39 or later: trial snapshot files use the marker `@@reason-git-snapshot@@`. |
| 1.8.2 | October 2026 | Claude Opus 4.8, Claude Opus 5, Claude Sonnet 5 and Claude Sonnet 5.5 join the price table: Anthropic's server-side refusal fallback serves declined Claude requests with them, and each step is priced by the model that served it. |
| 1.8.3 | October 2026 | GPT-6.1 Terra joins the price table at OpenAI's published rates. |
| 1.9 | October 2026 | The adapter (0.3.42 or later) requests `runtime/reason-agent-1.3` by default: Reason Agent 1.2's prompt and tools, plus continuing a response cut at the output cap, an append-only image history and a one-hour prompt cache on direct Anthropic requests. Its worker keeps a Bash command off the shell's argv, so `pkill -f` with a pattern from the command no longer kills the shell, and its agent tools add `bc`, `column`, `pkill`, `pgrep`, `free` and `which`. `runtime/reason-agent-1.2` and earlier releases are named explicitly. |
| 1.9.1 | October 2026 | Adapter 0.3.43 or later: since October 29, 2026 the Reason API starts every new API-key worker with direct access off, and earlier adapters' trials fail at worker startup (`execution_ineligible`). 0.3.43 turns it on for the trial's own worker. Scoring is unchanged. |
| 1.10 | November 2026 | Cost: `score.py` also lists what Reason charged (list price plus 25% on Reason-paid models, the `cost_usd` Harbor uploads), prices Anthropic one-hour cache writes at 2x input, and the methodology records how token counts and cost were checked against the gateway and OpenAI's billing. Trajectories name the script tool as the model saw it (`reason`, not `codemode`) from November 2, 2026. `run.sh` and `run-pass.sh` check the SWE-Atlas grader key before launching. Scores are unchanged. |
| 1.10.1 | November 2026 | GLM-5.3-Flash joins the price table at Z.ai's list price ($0.15 input, $0.03 cache read, $0.50 output per 1M tokens; Z.ai bills cache writes as input). Self-hosted GLM-5.3-Flash passes are priced as Z.ai would bill their tokens. |
| 1.10.2 | November 2026 | `adjudications.json` takes a third decision, `"scored_zero"`: an attempt that ended on the agent's side without a result (Reason `error_class` `stuck`, `agent_ended_without_text`) counts as a 0 attempt instead of waiting for a rerun, and `score.py` lists these attempts. A pass's published adjudications reproduce its score with the public `score.py`. Runs without the key score as before. |
| 1.10.3 | November 2026 | Claude Fable 5.2 joins the price table at Anthropic's list price ($8 input, $0.20 cache read, $10 five-minute cache write, $40 output per 1M tokens; one-hour writes at 2x input, as for every Anthropic model). Scores are unchanged. |

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
