# SWE-Atlas Codebase QnA

[SWE-Atlas QnA](https://labs.scale.com/leaderboard/sweatlas-qna) has 124
questions about large real codebases. The agent explores the code and runs it
to answer. An LLM judge grades each answer against a rubric written by an
expert. A task passes only if every rubric item passes.

Complete the [quick start in the main README](../README.md#quick-start) first.

## Grader key

The judge is Claude Opus 4.5. Export an Anthropic API key; `run.sh` passes it
to the grader through Anthropic's OpenAI-compatible API:

```bash
export ANTHROPIC_API_KEY=<YOUR-ANTHROPIC-KEY>
```

With plain `harbor run`, add the same three grader settings yourself:

```bash
--ve 'EVAL_API_KEY=${ANTHROPIC_API_KEY}' \
--ve EVAL_BASE_URL=https://api.anthropic.com/v1/ \
--ve EVAL_MODEL=claude-opus-4-5-20251101
```

The agent never sees the key. Grading costs are separate from the agent cost
that `score.py` reports.

## Run

```bash
./run.sh swe-atlas-qna
```

- **Dataset:** `scale-ai/swe-atlas-qna`, pinned by registry digest in [`run.sh`](../run.sh).
- **Where it runs:** 99 tasks on e2b and, at the same time, the 25 tasks in
  [`modal-tasks.txt`](modal-tasks.txt) on Modal: their images (maddy,
  paperless-ngx) break e2b's sandbox setup. Tasks ask for 16 CPUs and 16 GiB;
  every cloud trial runs at 8 / 8, e2b's limit, so both halves match.
- **Time:** the agent gets up to 3 hours per attempt, then grading takes up to
  15 minutes.
- **Score:** pass@1 over 3 attempts per task, using Scale's Task Resolve Rate.

Published leaderboard: <https://labs.scale.com/leaderboard/sweatlas-qna>.
Scale runs its leaderboard with its own agent and step limit, so those numbers
measure something different from Harbor pass@1.

## Citation

```bibtex
@misc{raghavendra2026sweatlasbenchmarkingcoding,
  title         = {SWE Atlas: Benchmarking Coding Agents Beyond Issue Resolution},
  author        = {Mohit Raghavendra and Soham Dan and Miguel Romero Calvo and Yannis Yiming He and Johannes Baptist Mols and Gautam Anand and Cole McCollum and Edgar Arakelyan and Vijay Bharadwaj and Andrew Park and Jeff Da and MohammadHossein Rezaei and Bing Liu and Brad Kenstler and Yunzhong He},
  year          = {2026},
  eprint        = {2605.08366},
  archivePrefix = {arXiv},
  primaryClass  = {cs.LG},
  url           = {https://arxiv.org/abs/2605.08366}
}
```
