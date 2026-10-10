# Terminal-Bench 4.0

[Terminal-Bench](https://www.tbench.ai/) has 66 hard tasks done entirely in a
terminal, ranging from systems and security work to science and data
pipelines. Each task has its own test suite. Version 4.0
([release notes](https://www.tbench.ai/news/terminal-bench-4-0)) is the version
used in the Artificial Analysis index v1.5.

Complete the [quick start in the main README](../README.md#quick-start) first, then run:

```bash
./run.sh terminal-bench
```

- **Dataset:** `terminal-bench/terminal-bench@4`, pinned by registry digest in
  [`run.sh`](../run.sh).
- **Where it runs:** 45 tasks on e2b and, at the same time, the 21 tasks in
  [`modal-tasks.txt`](modal-tasks.txt) on Modal. Those need an H100
  (`fp8-rmsnorm-gemm`, `jax-speedrun-gpu`, `math-eval-grader`), start several
  containers, need more than 8 CPUs / 8 GiB, or have a reference solution that
  fails on e2b. Each gets the resources it asks for. The GPU tasks can also run
  on a Lambda H100 host, in a `lambda` part
  ([methodology](../docs/METHODOLOGY.md#environment)).
- **Time:** the agent gets up to 8 hours per attempt.
- **Score:** pass@1 over the attempts per task. As Artificial Analysis does,
  an attempt that a judge finds reward hacking scores 0: `screening/screen.py
  --judge` runs the judge, and `score.py` reports the result as Screened.

Published leaderboard: <https://www.tbench.ai/leaderboard>.

## Citation

```bibtex
@inproceedings{merrill2026terminalbench,
  title     = {Terminal-Bench: Benchmarking Agents on Hard, Realistic Tasks in Command Line Interfaces},
  author    = {Mike A Merrill and Alexander Glenn Shaw and Nicholas Carlini and others},
  booktitle = {The Fourteenth International Conference on Learning Representations},
  year      = {2026},
  eprint    = {2601.11868},
  url       = {https://openreview.net/forum?id=a7Qa4CcHak}
}

@software{terminalbench2026v4,
  title   = {Terminal-Bench},
  version = {v4.0.0},
  author  = {Marten, Ryan and Shaw, Alex and Bercovich, Ivan and others},
  year    = {2026},
  month   = {aug},
  doi     = {10.5281/zenodo.22105681},
  url     = {https://www.tbench.ai/}
}
```
