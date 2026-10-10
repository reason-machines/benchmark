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
for every attempt. We recommend running the pinned harness release
`runtime/reason-v7-2026-10`, which never changes, so every rerun runs the same
harness; the adapter requests it by default. Our October 2026 results ran
earlier, on Reason's default harness at the time (`reason-c2-tools-v7`), which
changed during the runs; each Harbor job's trials name the harness they ran.
Each benchmark scores pass@1, averaged over three attempts per task, and the
Index is the equal-weight mean of the three. Timeouts score 0, provider refusals are redrawn
up to 10 times, and a Terminal-Bench attempt the reward-hacking judge fails
scores 0. See the [methodology](docs/METHODOLOGY.md) for the full rules and
their version history.

## Quick start

You need [uv](https://docs.astral.sh/uv/getting-started/installation/), Docker
and a [Reason API key](https://reasonmachines.ai/customize?tab=api) with `run`,
`sessions:read`, `deployment:read`, `devices:read`, `devices:write`,
`devices:use` and `org:write`.

```bash
uv tool install "harbor==0.22.0" --with "reason-machines-harbor>=0.3.19"
export REASON_API_KEY=<YOUR-REASON-KEY>

# For your own provider key, connect it under Models and use --model byok:openai:gpt-6-luna
harbor run --dataset datacurve/deep-swe-1-1 \
   --agent reasonmachines_harbor:ReasonAgent \
   --model openai/gpt-6-luna \
   --ak reasoning_effort=xhigh \
   --allow-agent-host api.reasonmachines.com \
   --allow-agent-host relay.reasonmachines.com
```

To run on e2b, with Modal for GPUs: [`run-pass.sh`](run-pass.sh) (all three) or [`run.sh`](run.sh) (one).

## Citation

```bibtex
@misc{reasonmachines2026benchmark,
  title        = {Reason on the Coding Agent Index},
  author       = {{Reason Machines}},
  year         = {2026},
  howpublished = {\url{https://github.com/reason-machines/benchmark}}
}
```
