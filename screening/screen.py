"""Screen one run for reward hacking: every trial of every Harbor job under jobs/<run>/.

Usage: python3 screening/screen.py [--judge] jobs/<run>

Every trial is scanned (checks.py) and its flags listed for a person to review. --judge
runs Artificial Analysis's reward hacking judge, `harbor analyze` with rubric.toml and
Claude Sonnet 5, on each passing Terminal-Bench trial, as they do. It needs
ANTHROPIC_API_KEY, Docker and Harbor; trials that already have a verdict are not judged
again. Results go to <run>/screening.json, and score.py scores an attempt the judge
FAILs as 0.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from checks import scan, task_facts

HERE = Path(__file__).resolve().parent
BENCHMARKS = ("deepswe", "swe-atlas-qna", "terminal-bench")
TASK_CACHE = Path("~/.cache/harbor/tasks/packages").expanduser()
# Artificial Analysis's judge model; Harbor's claude-code agent takes the provider prefix.
JUDGE_MODEL = "anthropic/claude-sonnet-5"
JUDGE_CONCURRENCY = 4


def trial_dirs(run: Path):
    for bench in BENCHMARKS:
        for result in sorted(run.glob(f"{bench}/*/*/*/result.json")):
            trial = json.loads(result.read_text())
            if "task_name" in trial:
                yield bench, result.parent, trial


def reward(trial: dict):
    return ((trial.get("verifier_result") or {}).get("rewards") or {}).get("reward")


def passed(trial: dict) -> bool:
    """Harbor's --passing: reward 1.0 and no exception."""
    return reward(trial) == 1.0 and not trial.get("exception_info")


def task_dir(trial: dict) -> Path | None:
    """The task's local copy, where `harbor analyze` looks for it; fetched into the cache if missing."""
    task = trial["config"]["task"]
    if task.get("path"):
        path = Path(task["path"]).expanduser()
    elif task.get("name") and (task.get("ref") or "").startswith("sha256:"):
        path = TASK_CACHE / task["name"] / task["ref"].removeprefix("sha256:")
        if not path.is_dir() and shutil.which("harbor"):
            subprocess.run(["harbor", "download", f"{task['name']}@{task['ref']}", "--cache"], capture_output=True)
    else:
        return None
    return path if path.is_dir() else None


def judge(run: Path, trials: dict[Path, str]) -> dict[Path, dict]:
    """`harbor analyze` on each trial, a few at a time; each is its own Harbor job under <run>/judge/."""
    out = run / "judge"
    out.mkdir(exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    pending, running, verdicts = list(trials.items()), [], {}
    while pending or running:
        while pending and len(running) < JUDGE_CONCURRENCY:
            trial, name = pending.pop(0)
            job = f"{name.replace('/', '-')}-{stamp}"
            print(f"Judging {name}: log in judge/{job}.log", file=sys.stderr)
            log = (out / f"{job}.log").open("w")
            command = ["harbor", "analyze", str(trial), "-m", JUDGE_MODEL, "-r", str(HERE / "rubric.toml"),
                       "-o", str(out), "--job-name", job, "-q"]
            running.append((trial, job, subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)))
        trial, job, process = running.pop(0)
        process.wait()
        report = out / job / "analysis.json"
        result = (json.loads(report.read_text())["results"] or [{}])[0] if report.exists() else {}
        check = (result.get("checks") or {}).get("reward_hacking")
        verdict = ({"outcome": check["outcome"], "explanation": check["explanation"], "cost_usd": result.get("cost_usd")}
                   if check else {"outcome": "error",
                                  "explanation": result.get("error") or f"harbor analyze exited {process.returncode}"})
        verdicts[trial] = verdict | {"model": JUDGE_MODEL, "analysis": f"judge/{job}"}
    return verdicts


def redacted(rows: list[dict], source: str) -> str:
    """Total redactions counted from one source, with its trial count; "n/a" if none used it."""
    rows = [e for e in rows if e["markers"].get("redactions_from") == source]
    return f"{sum(e['markers']['redacted'] for e in rows)} ({len(rows)} trials)" if rows else "n/a"


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("run", type=Path)
    parser.add_argument("--judge", action="store_true", help="judge the passing Terminal-Bench trials")
    args = parser.parse_args()
    run = args.run.resolve()
    output = run / "screening.json"
    previous = json.loads(output.read_text())["trials"] if output.exists() else {}

    screened, dirs = {}, {}
    for bench, trial_dir, trial in trial_dirs(run):
        task = task_dir(trial)
        flags, markers = scan(bench, trial_dir, task_facts(task))
        screened[trial["id"]] = {
            "path": str(trial_dir.relative_to(run)), "benchmark": bench, "task": trial["task_name"],
            "reward": reward(trial), "passed": passed(trial), "task_dir": str(task) if task else None,
            "flags": flags, "markers": markers, "judge": (previous.get(trial["id"]) or {}).get("judge"),
        }
        dirs[trial["id"]] = trial_dir
    if not screened:
        sys.exit(f"No trials under {run}")

    if args.judge:
        wanted = {dirs[i]: e["path"] for i, e in screened.items()
                  if e["benchmark"] == "terminal-bench" and e["passed"]
                  and (e["judge"] or {}).get("outcome") not in ("pass", "fail", "not_applicable")}
        missing = [screened[i]["task"] for i, d in dirs.items() if d in wanted and not screened[i]["task_dir"]]
        if missing:
            # Without the task, the judge would not see its tests or reference solution.
            sys.exit(f"Not in Harbor's cache (harbor download <task>@<digest> --cache): {' '.join(missing)}")
        if not os.environ.get("ANTHROPIC_API_KEY") or not shutil.which("harbor"):
            sys.exit("The judge needs ANTHROPIC_API_KEY and Harbor.")
        verdicts = judge(run, wanted)
        # The judge sometimes writes its verdict outside its output folder; one retry recovers it.
        verdicts |= judge(run, {d: wanted[d] for d, v in verdicts.items() if v["outcome"] == "error"})
        ids = {d: i for i, d in dirs.items()}
        for trial_dir, verdict in verdicts.items():
            screened[ids[trial_dir]]["judge"] = verdict

    output.write_text(json.dumps({"rubric": "screening/rubric.toml", "trials": screened}, indent=2) + "\n")
    # Redactions the server counted, then, for older trajectories, redaction-like text
    # (which includes task content, so it over-counts).
    print("| Benchmark | Trials | Passing | Flagged (passing) | Judged | Judge FAIL | Redactions "
          "| Redaction text matches (older trajectories) | Truncated markers |")
    print("|---|---|---|---|---|---|---|---|---|")
    for bench in BENCHMARKS:
        rows = [e for e in screened.values() if e["benchmark"] == bench]
        if rows:
            judged = [e for e in rows if e["judge"]]
            print(f"| {bench} | {len(rows)} | {sum(e['passed'] for e in rows)} "
                  f"| {sum(bool(e['flags']) for e in rows)} ({sum(bool(e['flags']) and e['passed'] for e in rows)}) "
                  f"| {len(judged)} | {sum(e['judge']['outcome'] == 'fail' for e in judged)} "
                  f"| {redacted(rows, 'fidelity')} | {redacted(rows, 'text matches')} "
                  f"| {sum(e['markers']['truncated'] for e in rows)} |")
    # Only an attempt that scored can be a reward hack worth a look.
    for entry in sorted(screened.values(), key=lambda e: e["path"]):
        verdict = (entry["judge"] or {}).get("outcome")
        if (entry["reward"] or 0) > 0 and (entry["flags"] or verdict not in (None, "pass")):
            print(f"Review {entry['path']} (reward {entry['reward']}): judge {verdict or 'not run'}; "
                  f"flags: {', '.join(entry['flags']) or 'none'}", file=sys.stderr)
    print(f"Wrote {output}", file=sys.stderr)


if __name__ == "__main__":
    main()
