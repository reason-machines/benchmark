"""Score one run: every Harbor job for each benchmark under jobs/<run>/.

Usage: python score.py [--attempts K] [--strict] [--expect R] jobs/<run>

Jobs under <benchmark>/all are one whole run; jobs under <benchmark>/e2b, /modal and
/lambda are parts of a split run. A run may hold any number of jobs per part: one job
for every task, one job per task, or one job per attempt.

Each task has K attempt slots (--attempts, else the largest n_attempts of the
benchmark's jobs). A task's attempts are taken in order (job name, then start time),
and each result fills the next empty slot, so reruns fill slots the earlier jobs left
empty and never replace a result:
- a graded attempt scores its verifier reward;
- an attempt past its agent or verifier time limit, or that Reason refused
  (instruction_blocked) on every try, scores 0;
- a provider refusal is redrawn: a slot whose draw is refused 1 + 10 times in a row
  scores 0;
- anything else (an infrastructure error, no reward, DeepSWE's grader-crash reward
  of -1) is not a result, and the slot waits for a rerun.
A slot still empty scores 0, and the task is listed for rerun.

<run>/adjudications.json, if present, records decisions the trial files can't show,
each keyed by a trial or job folder relative to <run>, with the reason as the value:
  {"void": {...}, "refused": {...}}
"void" attempts ran under a confirmed harness or environment bug and never count;
the results file discloses them. "refused" marks provider refusals that Reason did
not classify as provider_policy_refusal.

Pass@1 follows the Artificial Analysis formula: average each task's slot scores, then
average across tasks. The index is the mean of the three benchmarks; its interval
resamples each benchmark's tasks together. With more than one slot per task, the
attempt spread is the lowest and highest pass@1 of a single slot (every task's first
attempt, every task's second, and so on). If screening/screen.py has written
<run>/screening.json, the table adds the screened pass@1 and its interval: an attempt
its reward hacking judge FAILs scores 0, as Artificial Analysis scores it.

Below the table, Builds lists what the counted attempts ran on, from each trial's
config and the adapter's agent/deployment.json and agent/receipt.json. --strict is the
gate before publishing: it fails unless every benchmark has every task with every slot
filled, and the counted attempts share one model, reasoning effort, adapter version,
runtime profile, harness digest and runtime feature set. Server and worker builds roll
with production deploys, so they are listed, not gated. Each attempt's trajectory
(agent/trajectory.json) must also show it ran on one server build ("build per step")
and was exported whole, masking only injected secrets and Reason-issued tokens ("trajectory fidelity"); attempts
that don't, or whose trajectory doesn't record it, are listed and fail --strict.

Cost per attempt prices the token counts in the attempt's trajectory, its subagents'
included, one model response at a time from PRICES: uncached input, cache reads, cache
writes and output, at the higher rates when a request's input is over 272k tokens.
The responses must add up to the token totals the Session recorded ("token usage"
complete); otherwise the attempt's reported cost_usd is used and the table says how
many were. Below Builds, the cost of each token kind is listed for the priced attempts.
--strict also requires complete token usage.

--expect R checks a preflight: it fails and lists every task whose pass@1 is not R
(1 for the oracle agent, which runs each task's reference solution; 0 for nop).
"""
import argparse
import json
import random
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

EXPECTED_TASKS = {"deepswe": 113, "swe-atlas-qna": 124, "terminal-bench": 66}
PARTS = ("e2b", "modal", "lambda")
REFUSAL_REDRAWS = 10
TIMEOUTS = {"AgentTimeoutError", "VerifierTimeoutError"}
# Build fields every counted attempt must share (--strict), then the ones only listed.
INVARIANT = ("model", "reasoning effort", "adapter", "runtime profile", "harness digest", "runtime features")
LISTED = ("environment", "server commit", "worker")
# Per-attempt trajectory checks (--strict) and the value each must have; other values are listed.
CHECKED = {"build per step": "one", "trajectory fidelity": "complete", "token usage": "complete"}
# USD per million tokens: uncached input, cache read, cache write, output; then the rates for a
# request whose input is over LONG_CONTEXT_TOKENS. OpenAI's prices, which Reason and Pi also bill at.
PRICES = {
    "gpt-6-luna": ((0.10, 0.01, 0.125, 0.50), (0.20, 0.02, 0.25, 0.75)),
    "gpt-6-astra": ((10.0, 1.0, 12.5, 50.0), (20.0, 2.0, 25.0, 75.0)),
}
LONG_CONTEXT_TOKENS = 272_000
TOKEN_KINDS = ("uncached input", "cache read", "cache write", "output")
# The benchmark redaction tier's markers: secret values we inject, and Reason-issued token
# shapes. Any other marker means content was masked that the methodology says is kept.
SECRET_MARKERS = {"[redacted-secret]", "[redacted-run-token]", "rmt_***", "reason_***", "ara_***",
                  "reason_ssh_install_***", "ara_ssh_install_***", "rslack_[redacted]"}


def jobs_for(bench_dir: Path) -> list[Path]:
    """Job directories, oldest first: the whole runs if any, else every part's jobs."""
    whole = sorted(p for p in (bench_dir / "all").glob("*") if p.is_dir())
    parts = [p for part in PARTS for p in (bench_dir / part).glob("*") if p.is_dir()]
    if whole:
        if parts:
            print(f"Warning: {bench_dir.name} scores only its all/ jobs; {len(parts)} part jobs are ignored.",
                  file=sys.stderr)
        return whole
    return sorted(parts, key=lambda p: p.name)


def trials(job: Path):
    for path in job.glob("*/result.json"):
        trial = json.loads(path.read_text())
        if "task_name" in trial:
            yield path.parent, trial


def configured_attempts(job: Path) -> int:
    try:
        return int(json.loads((job / "config.json").read_text())["n_attempts"])
    except (OSError, ValueError, KeyError, TypeError):
        counts = defaultdict(int)
        for _, trial in trials(job):
            counts[trial["task_name"]] += 1
        return max(counts.values(), default=0)


def read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return value if isinstance(value, dict) else {}


def builds_per_step(agent_extra: dict, fidelity: dict) -> str | None:
    """"one" when every agent step recorded the same server commit; None for older exports."""
    commits, without = agent_extra.get("server_commits"), fidelity.get("agent_steps_without_build")
    if not isinstance(commits, list) or not isinstance(without, int):
        return None
    return "one" if len(commits) <= 1 and without == 0 else "spans builds"


def trajectory_fidelity(fidelity: dict) -> str | None:
    """"complete" when no tool result fell back to an excerpt and only injected secrets and
    Reason-issued tokens were masked; None for older exports, which don't count redactions as they apply them."""
    excerpts, redactions = fidelity.get("excerpt_tool_events"), fidelity.get("redactions")
    if not isinstance(excerpts, int) or not isinstance(redactions, dict):
        return None
    masks = sorted(marker for marker, n in redactions.items() if marker not in SECRET_MARKERS and n)
    problems = (["excerpts"] if excerpts else []) + ([f"masks {' '.join(masks)}"] if masks else [])
    return ", ".join(problems) or "complete"


def priced(trajectory: dict) -> tuple[list[float] | None, str | None]:
    """The cost of each token kind for a trajectory and its subagents, and its token usage:
    "complete" when every model response is priced and they add up to the Session's totals,
    otherwise why not (the cost is then None); None for an export without per-response usage."""
    if not any(step.get("metrics") for step in trajectory.get("steps") or []):
        return None, None
    model = str((trajectory.get("agent") or {}).get("model_name"))
    costs, prompt, completion = [0.0] * len(TOKEN_KINDS), 0, 0
    for step in trajectory["steps"]:
        if not (metrics := step.get("metrics")):
            continue
        name = str(step.get("model_name") or model).rsplit(":", 1)[-1].rsplit("/", 1)[-1]
        if name not in PRICES:
            return None, f"no price for {name}"
        tokens = (metrics.get("prompt_tokens"), metrics.get("cached_tokens"),
                  (metrics.get("extra") or {}).get("cache_write_tokens"), metrics.get("completion_tokens"))
        # The long-context rates apply per request, so a step must hold one response.
        if None in tokens or (step.get("llm_call_count") or 1) != 1:
            return None, "incomplete"
        prompt_tokens, cached, written, output = tokens
        rates = PRICES[name][prompt_tokens > LONG_CONTEXT_TOKENS]
        for i, n in enumerate((prompt_tokens - cached - written, cached, written, output)):
            costs[i] += n * rates[i] / 1_000_000
        prompt, completion = prompt + prompt_tokens, completion + output
    final = trajectory.get("final_metrics") or {}
    session = (final.get("extra") or {}).get("session_totals") or final
    if (prompt, completion) != (session.get("total_prompt_tokens"), session.get("total_completion_tokens")):
        return None, "incomplete"
    for subagent in trajectory.get("subagent_trajectories") or []:
        sub_costs, usage = priced(subagent)
        if sub_costs is None:
            return None, usage or "incomplete"
        costs = [a + b for a, b in zip(costs, sub_costs)]
    return costs, "complete"


def build(trial_dir: Path, trial: dict, trajectory: dict) -> dict[str, str]:
    """What one attempt ran on; "unknown" where its files don't say."""
    config = trial.get("config") or {}
    agent, environment = config.get("agent") or {}, config.get("environment") or {}
    deployment = read_json(trial_dir / "agent" / "deployment.json")
    receipt = read_json(trial_dir / "agent" / "receipt.json")
    agent_extra = (trajectory.get("agent") or {}).get("extra") or {}
    fidelity = (trajectory.get("extra") or {}).get("fidelity") or {}
    profile = receipt.get("server_experimental_runtime_profile") or receipt.get("runtime_profile")
    fields = {
        "model": agent.get("model_name"),
        "reasoning effort": (agent.get("kwargs") or {}).get("reasoning_effort"),
        "adapter": (trial.get("agent_info") or {}).get("version"),
        "runtime profile": profile,
        "harness digest": (agent_extra.get("harness") or {}).get("profile_digest"),
        "runtime features": ",".join(receipt.get("runtime_features") or []) or ("none" if receipt else None),
        "environment": environment.get("import_path") or environment.get("type"),
        "server commit": (deployment.get("commit_sha") or "")[:10] or None,
        "worker": receipt.get("cli_version"),
        "build per step": builds_per_step(agent_extra, fidelity),
        "trajectory fidelity": trajectory_fidelity(fidelity),
        "token usage": priced(trajectory)[1],
    }
    return {name: str(value) if value is not None else "unknown" for name, value in fields.items()}


def agent_minutes(trial: dict) -> float | None:
    execution = trial.get("agent_execution") or {}
    try:
        start, end = (datetime.fromisoformat(execution[k]) for k in ("started_at", "finished_at"))
    except (KeyError, TypeError, ValueError):
        return None
    return (end - start).total_seconds() / 60


def outcome(trial_dir: Path, trial: dict, root: Path, adjudications: dict) -> tuple[str, float]:
    """("result", score), ("refused", 0) or ("void", 0) for one attempt."""
    relative = trial_dir.relative_to(root)
    keys = {str(p) for p in (relative, *relative.parents)}
    if keys & adjudications.get("void", {}).keys():
        return "void", 0.0
    session = {}
    try:
        session = json.loads((trial_dir / "agent" / "session.json").read_text())
    except (OSError, ValueError):
        pass
    if session.get("error_class") == "provider_policy_refusal" or str(relative) in adjudications.get("refused", {}):
        return "refused", 0.0
    exception = trial.get("exception_info") or {}
    if exception.get("exception_type") in TIMEOUTS:
        return "result", 0.0
    reward = ((trial.get("verifier_result") or {}).get("rewards") or {}).get("reward")
    if reward is not None and float(reward) >= 0:
        return "result", float(reward)
    if "instruction_blocked" in (exception.get("exception_message") or ""):
        return "result", 0.0
    return "void", 0.0


def fill_slots(attempts: list[tuple[str, float, tuple[Path, dict]]], k: int) -> list[tuple[float, tuple[Path, dict] | None]]:
    """The first k results in order; a slot refused 1 + REFUSAL_REDRAWS times in a row scores 0."""
    slots, refused = [], 0
    for kind, value, trial in attempts:
        if kind == "refused":
            refused += 1
            if refused > REFUSAL_REDRAWS:
                slots.append((0.0, None))
                refused = 0
        elif kind == "result":
            slots.append((value, trial))
            refused = 0
        if len(slots) == k:
            break
    return slots


def ci95(*benchmarks: list[float]) -> tuple[float, float]:
    """95% interval of the mean of the benchmarks' task means, from 2,000 bootstrap
    resamples of each benchmark's tasks."""
    rng = random.Random(0)
    boot = sorted(sum(sum(rng.choices(means, k=len(means))) / len(means) for means in benchmarks) / len(benchmarks)
                  for _ in range(2000))
    return boot[49], boot[1949]


def score(jobs: list[Path], failed: set[str], root: Path, adjudications: dict, k: int | None = None):
    k = k or max(map(configured_attempts, jobs), default=0)
    by_task = defaultdict(list)
    for index, job in enumerate(jobs):
        for trial_dir, trial in trials(job):
            order = (index, trial.get("started_at") or "", trial_dir.name)
            by_task[trial["task_name"]].append((order, *outcome(trial_dir, trial, root, adjudications),
                                                (trial_dir, trial)))
    if not by_task or not k:
        return None
    task_scores, screened_means, slot_rewards, costs, minutes, short = {}, [], [], [], [], {}
    by_kind, reported = [0.0] * len(TOKEN_KINDS), 0
    builds, flagged = defaultdict(Counter), defaultdict(list)
    for task, attempts in by_task.items():
        slots = fill_slots([a[1:] for a in sorted(attempts, key=lambda a: a[0])], k)
        if len(slots) < k:
            short[task] = k - len(slots)
        rewards = [r for r, _ in slots] + [0.0] * (k - len(slots))
        screened = [0.0 if a is not None and a[1]["id"] in failed else r for r, a in slots] + [0.0] * (k - len(slots))
        task_scores[task] = sum(rewards) / k
        screened_means.append(sum(screened) / k)
        slot_rewards.append(rewards)
        for _, attempt in slots:
            if attempt is None:
                continue
            trial_dir, trial = attempt
            trajectory = read_json(trial_dir / "agent" / "trajectory.json")
            if (kinds := priced(trajectory)[0]) is not None:
                costs.append(sum(kinds))
                by_kind = [a + b for a, b in zip(by_kind, kinds)]
            elif (cost := (trial.get("agent_result") or {}).get("cost_usd")) is not None:
                costs.append(cost)
                reported += 1
            if (spent := agent_minutes(trial)) is not None:
                minutes.append(spent)
            for name, value in build(trial_dir, trial, trajectory).items():
                builds[name][value] += 1
                if name in CHECKED and value != CHECKED[name]:
                    flagged[f"{name}: {value}"].append(str(trial_dir.relative_to(root)))
    task_means = list(task_scores.values())
    by_slot = [sum(rewards[i] for rewards in slot_rewards) / len(slot_rewards) for i in range(k)]
    return {
        "pass_at_1": sum(task_means) / len(task_means),
        "screened": sum(screened_means) / len(screened_means),
        "ci95": ci95(task_means),
        "ci95_screened": ci95(screened_means),
        "task_scores": task_scores,
        "screened_means": screened_means,
        "attempt_spread": (min(by_slot), max(by_slot)) if k > 1 else None,
        "tasks": len(task_means),
        "attempts_per_task": k,
        "attempts": k * len(task_means),
        "cost_per_attempt": sum(costs) / len(costs) if costs else None,
        "costed_attempts": len(costs),
        "reported_cost_attempts": reported,
        "cost_by_kind": by_kind,
        "counted_attempts": sum(builds["model"].values()),
        "agent_minutes": statistics.median(minutes) if minutes else None,
        "builds": builds,
        "flagged": dict(sorted(flagged.items())),
        "short": dict(sorted(short.items())),
    }


def builds_table(builds: dict[str, Counter]) -> list[str]:
    lines = ["", "Builds of the counted attempts:", "", "| Field | Values |", "|---|---|"]
    for name in (*INVARIANT, *LISTED, *CHECKED):
        counts = builds.get(name) or Counter()
        values = ", ".join(f"{value} ({n})" for value, n in counts.most_common())
        lines.append(f"| {name} | {f'{len(counts)}: ' if len(counts) > 1 else ''}{values} |")
    return lines


def cost_table(scores: dict[str, dict]) -> list[str]:
    lines = ["", "Cost of the priced attempts by token kind:", "",
             "| Benchmark | Priced attempts | " + " | ".join(kind.capitalize() for kind in TOKEN_KINDS) + " |",
             "|---|---|" + "---|" * len(TOKEN_KINDS)]
    for bench, result in scores.items():
        kinds, total = result["cost_by_kind"], sum(result["cost_by_kind"])
        cells = " | ".join(f"${cost:,.2f} ({cost / total:.0%})" if total else "n/a" for cost in kinds)
        lines.append(f"| {bench} | {result['costed_attempts'] - result['reported_cost_attempts']} | {cells} |")
    return lines


def incomplete(scores: dict[str, dict]) -> list[str]:
    problems = [f"{bench} has no results" for bench in EXPECTED_TASKS if bench not in scores]
    for bench, result in scores.items():
        if result["tasks"] < EXPECTED_TASKS[bench]:
            problems.append(f"{bench} has results for {result['tasks']} of {EXPECTED_TASKS[bench]} tasks")
        if result["short"]:
            problems.append(f"{bench} has {sum(result['short'].values())} empty slots")
    return problems


def mixed(builds: dict[str, Counter]) -> list[str]:
    return ([f"counted attempts mix {len(builds[name])} values of {name}" for name in INVARIANT if len(builds[name]) > 1]
            + [f"{builds[name]['unknown']} counted attempts don't record their {name}"
               for name in (*INVARIANT, *CHECKED) if builds[name]["unknown"]]
            + [f"{n} counted attempts have {name}: {value}" for name, ok in CHECKED.items()
               for value, n in builds[name].items() if value not in (ok, "unknown")])


def main(root: Path, attempts: int | None = None, strict: bool = False, expect: float | None = None) -> int:
    path = root / "screening.json"
    screening = json.loads(path.read_text())["trials"] if path.exists() else None
    failed = {i for i, e in (screening or {}).items() if (e.get("judge") or {}).get("outcome") == "fail"}
    path = root / "adjudications.json"
    adjudications = json.loads(path.read_text()) if path.exists() else {}
    column = " Screened | Screened 95% CI |" if screening is not None else ""
    scores, builds = {}, defaultdict(Counter)
    print(f"| Benchmark | Jobs | Pass@1 | 95% CI |{column} Attempt spread | Cost / attempt | Agent time | Tasks | Attempts |")
    print("|---|---|---|" + "---|" * (8 if column else 6))
    for bench, expected in EXPECTED_TASKS.items():
        jobs = jobs_for(root / bench)
        result = score(jobs, failed, root, adjudications, attempts) if jobs else None
        if result is None:
            continue
        scores[bench] = result
        for name, counts in result["builds"].items():
            builds[name] += counts
        cost = "n/a" if result["cost_per_attempt"] is None else f"${result['cost_per_attempt']:.3f}"
        if result["cost_per_attempt"] is not None and result["costed_attempts"] < result["counted_attempts"]:
            cost += f" ({result['costed_attempts']} of {result['counted_attempts']})"
        if result["reported_cost_attempts"]:
            cost += f" ({result['reported_cost_attempts']} reported)"
        spread = "n/a" if result["attempt_spread"] is None else "{:.1%}–{:.1%}".format(*result["attempt_spread"])
        spent = "n/a" if result["agent_minutes"] is None else f"{result['agent_minutes']:.0f} min"
        low, high = result["ci95"]
        names = ", ".join(sorted({job.parent.name for job in jobs})) + f" ({len(jobs)} jobs)"
        s_low, s_high = result["ci95_screened"]
        screened = f" {result['screened']:.1%} | {s_low:.1%}–{s_high:.1%} |" if column else ""
        print(f"| {bench} | {names} | {result['pass_at_1']:.1%} | {low:.1%}–{high:.1%} |{screened} "
              f"{spread} | {cost} | {spent} | {result['tasks']}/{expected} | {result['attempts']} |")
        if result["tasks"] < expected:
            print(f"Warning: {bench} has results for {result['tasks']} of {expected} tasks.", file=sys.stderr)
        if result["short"]:
            missing = " ".join(f"{task}({n})" for task, n in result["short"].items())
            print(f"{bench} tasks with empty slots of {result['attempts_per_task']} (scored 0; rerun with -i): "
                  f"{missing}", file=sys.stderr)
        for check, paths in result["flagged"].items():
            print(f"{bench} counted attempts with {check}: {' '.join(paths)}", file=sys.stderr)
    if len(scores) == len(EXPECTED_TASKS):
        index = sum(s["pass_at_1"] for s in scores.values()) / len(scores)
        low, high = ci95(*(list(s["task_scores"].values()) for s in scores.values()))
        screened = ""
        if column:
            s_low, s_high = ci95(*(s["screened_means"] for s in scores.values()))
            screened = f" **{sum(s['screened'] for s in scores.values()) / len(scores) * 100:.1f}** " \
                       f"| {s_low * 100:.1f}–{s_high * 100:.1f} |"
        print(f"| **Index** | | **{index * 100:.1f}** | {low * 100:.1f}–{high * 100:.1f} |{screened} | | | | |")
    if scores:
        print("\n".join(builds_table(builds) + cost_table(scores)))
    status = 0
    if strict and (problems := incomplete(scores) + mixed(builds)):
        print("Not publishable (--strict): " + "; ".join(problems) + ".", file=sys.stderr)
        status = 1
    if expect is not None:
        wrong = {f"{bench}/{task}": value for bench, result in scores.items()
                 for task, value in result["task_scores"].items() if value != expect}
        if wrong or (problems := incomplete(scores)):
            listed = " ".join(f"{task}({value:.2f})" for task, value in sorted(wrong.items()))
            print(f"Preflight failed: expected pass@1 {expect:g} on every task; {len(wrong)} differ"
                  + (f": {listed}" if listed else "") + "".join(f"; {p}" for p in incomplete(scores)) + ".",
                  file=sys.stderr)
            status = 1
    return status


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--attempts", type=int, help="attempt slots per task (default: the jobs' largest n_attempts)")
    parser.add_argument("--strict", action="store_true",
                        help="fail unless the run is complete and its counted attempts share one configuration, "
                             "each on one server build with a complete trajectory and token usage")
    parser.add_argument("--expect", type=float, metavar="R",
                        help="fail unless every task scores R (preflight: 1 for oracle, 0 for nop)")
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    sys.exit(main(args.run, args.attempts, args.strict, args.expect))
