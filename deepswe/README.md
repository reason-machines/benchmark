# DeepSWE v1.1

[DeepSWE](https://deepswe.datacurve.ai/) has 113 long feature-building tasks
in real open-source repositories, across several languages. A hidden test
suite grades each task. v1.1 is the version used in the Artificial Analysis
index.

Complete the [quick start in the main README](../README.md#quick-start) first, then run:

```bash
./run.sh deepswe
```

- **Dataset:** `datacurve/deep-swe-1-1`, pinned by registry digest in [`run.sh`](../run.sh).
- **Where it runs:** 111 tasks on e2b and, at the same time, the 2 tasks in
  [`modal-tasks.txt`](modal-tasks.txt) on Modal: their grader needs the grading
  image's environment, which e2b doesn't apply. Each asks for 2 CPUs and 8 GiB.
- **Time:** the agent gets up to 1.5 hours per attempt, then grading takes up
  to 30 minutes.
- **Network:** tasks run without internet. The adapter only opens the Reason
  API and relay hosts that `run.sh` passes to Harbor.
- **Score:** pass@1 over 3 attempts per task. A task passes only if every
  hidden test passes.

Published leaderboard: <https://deepswe.datacurve.ai/>.

## Citation

```bibtex
@misc{huang2026deepswe,
  title         = {DeepSWE: Measuring Frontier Coding Agents on Original, Long-Horizon Engineering Tasks},
  author        = {Wenqi Huang and Charley Lee and Leonard Tng and Serena Ge},
  year          = {2026},
  eprint        = {2607.07946},
  archivePrefix = {arXiv},
  primaryClass  = {cs.SE},
  url           = {https://arxiv.org/abs/2607.07946}
}

@misc{datacurve2026deepswev11,
  title  = {DeepSWE v1.1: a cleaner, more reproducible benchmark for frontier coding agents},
  author = {Wenqi Huang and Peter Jiang},
  year   = {2026},
  url    = {https://github.com/datacurve-ai/deep-swe}
}
```
