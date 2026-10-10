"""score.py on small Harbor job trees. Run: python3 -m unittest discover tests"""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import score  # noqa: E402


class Tree:
    """A jobs/<run>/ folder with Harbor's job and trial layout."""

    def __init__(self, root: Path):
        self.root = root
        self.clock = 0

    def job(self, bench: str, part: str, name: str, n_attempts: int, *attempts: tuple[str, dict]):
        job = self.root / bench / part / name
        job.mkdir(parents=True)
        (job / "config.json").write_text(json.dumps({"n_attempts": n_attempts}))
        for index, (task, fields) in enumerate(attempts):
            self.clock += 1
            trial = job / f"{task}__{name}{index}"
            (trial / "agent").mkdir(parents=True)
            result = {"id": f"{name}-{index}", "task_name": task, "started_at": f"2026-10-07T00:00:{self.clock:02d}Z",
                      "agent_result": {"cost_usd": fields.get("cost", 1.0)}, "exception_info": None,
                      "config": {"agent": {"model_name": "openai/gpt-6-luna", "kwargs": {"reasoning_effort": "xhigh"}},
                                 "environment": {"import_path": f"env:{part}"}},
                      "agent_info": {"version": fields.get("adapter", "0.3.16")},
                      "agent_execution": {"started_at": "2026-10-07T01:00:00Z",
                                          "finished_at": f"2026-10-07T01:{fields.get('minutes', 10):02d}:00Z"}}
            if "reward" in fields:
                result["verifier_result"] = {"rewards": {"reward": fields["reward"]}}
            if "error" in fields:
                result["exception_info"] = {"exception_type": fields["error"], "exception_message": fields.get("message", "")}
            (trial / "result.json").write_text(json.dumps(result))
            if fields.get("refused"):
                (trial / "agent" / "session.json").write_text(json.dumps({"error_class": "provider_policy_refusal"}))
            if "trajectory" in fields:
                (trial / "agent" / "trajectory.json").write_text(json.dumps(fields["trajectory"]))
            (trial / "agent" / "deployment.json").write_text(json.dumps({"commit_sha": fields.get("commit", "c" * 40)}))
            (trial / "agent" / "receipt.json").write_text(json.dumps({
                "cli_version": "0.2.121", "runtime_features": [],
                "server_experimental_runtime_profile": fields.get("profile", "runtime/reason-c2-tools-v7")}))
        return job

    def score(self, bench: str, attempts: int | None = None, failed=frozenset()):
        path = self.root / "adjudications.json"
        adjudications = json.loads(path.read_text()) if path.exists() else {}
        return score.score(score.jobs_for(self.root / bench), set(failed), self.root, adjudications, attempts)


GRADED = {"reward": 1.0}
FAILED = {"reward": 0.0}
ERROR = {"error": "RuntimeError"}
REFUSED = {"error": "ReasonSessionTerminalError", "refused": True}


def response(prompt=1_000, cached=900, written=50, output=10):
    """An agent step holding one model response's usage, as the export writes it."""
    return {"step_id": 2, "source": "agent", "message": "", "llm_call_count": 1,
            "metrics": {"prompt_tokens": prompt, "cached_tokens": cached, "completion_tokens": output,
                        "extra": {"cache_write_tokens": written}}}


def usage(*responses, model="byok:openai:gpt-6-astra", subagents=(), totals=None):
    """The usage fields of an export: its responses, and the Session's totals (theirs, unless given)."""
    prompt = sum(r["metrics"]["prompt_tokens"] for r in responses)
    completion = sum(r["metrics"]["completion_tokens"] for r in responses)
    return {"agent": {"name": "reason", "model_name": model}, "steps": list(responses),
            "final_metrics": {"total_prompt_tokens": prompt, "total_completion_tokens": completion, **(totals or {})},
            **({"subagent_trajectories": list(subagents)} if subagents else {})}


def trajectory(commits=("c" * 40,), without_build=0, excerpts=0, redactions=None, digest="sha256:aaa"):
    """An ATIF trajectory with the fields score.py reads; None drops a field, as older exports do."""
    agent_extra = {"harness": {"runtime_profile": "runtime/reason-v7-2026-10", "profile_digest": digest}}
    fidelity = {"excerpt_tool_events": excerpts, "redactions": {"[redacted-secret]": 2} if redactions is None else redactions,
                "agent_steps_without_build": without_build}
    if commits is not None:
        agent_extra["server_commits"] = list(commits)
    exported = usage(response())
    return {**exported, "agent": {**exported["agent"], "extra": agent_extra},
            "steps": [{"step_id": 1, "source": "system", "message": "You are Reason."}, *exported["steps"]],
            "extra": {"fidelity": {k: v for k, v in fidelity.items() if v is not None}}}


class ScoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.tree = Tree(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_per_pass_layout_scores_as_before(self):
        # One job for every task, then a rerun of the task left without a grade. The values
        # are what score.py gave before slots: a task's attempts come from its first job with
        # a grade, and an attempt without one scores 0.
        t = self.tree
        t.job("deepswe", "e2b", "20261004T000000Z", 3, ("a", GRADED), ("a", ERROR), ("a", FAILED),
              ("b", ERROR), ("b", ERROR), ("b", {"reward": -1}), ("c", GRADED), ("c", GRADED), ("c", GRADED))
        t.job("deepswe", "modal", "20261004T000100Z", 3, ("d", FAILED), ("d", FAILED), ("d", GRADED))
        t.job("deepswe", "e2b", "20261005T000000Z", 3, ("b", GRADED), ("b", FAILED), ("b", GRADED))
        result = t.score("deepswe")
        self.assertEqual(result["attempts_per_task"], 3)
        self.assertAlmostEqual(result["pass_at_1"], (1 / 3 + 2 / 3 + 1 + 1 / 3) / 4)
        self.assertEqual((result["tasks"], result["attempts"]), (4, 12))
        self.assertEqual(result["short"], {"a": 1})

    def test_one_attempt_pass_with_reruns_scores_as_before(self):
        t = self.tree
        t.job("terminal-bench", "e2b", "20261004T000000Z", 1, ("a", ERROR), ("b", GRADED), ("c", FAILED))
        t.job("terminal-bench", "modal", "20261004T000001Z", 1, ("d", ERROR))
        t.job("terminal-bench", "e2b", "20261004T120000Z", 1, ("a", GRADED))
        t.job("terminal-bench", "modal", "20261004T120001Z", 1, ("d", ERROR))
        result = t.score("terminal-bench")
        self.assertAlmostEqual(result["pass_at_1"], (1 + 1 + 0 + 0) / 4)
        self.assertEqual(result["short"], {"d": 1})

    def test_slots_combine_across_one_attempt_jobs_and_parts(self):
        t = self.tree
        t.job("terminal-bench", "e2b", "20261007T000000Z-a", 3, ("a", GRADED), ("a", FAILED), ("a", GRADED))
        t.job("terminal-bench", "modal", "20261007T000001Z-b-m1", 1, ("b", GRADED))
        t.job("terminal-bench", "modal", "20261007T000002Z-b-m2", 1, ("b", ERROR))
        t.job("terminal-bench", "modal", "20261007T000003Z-b-m3", 1, ("b", FAILED))
        t.job("terminal-bench", "lambda", "20261007T050000Z-b-r1", 1, ("b", GRADED))
        t.job("terminal-bench", "lambda", "20261007T060000Z-b-r2", 1, ("b", GRADED))
        result = t.score("terminal-bench")
        # b: the m2 error leaves a slot; the first lambda rerun fills it, the second is not counted.
        self.assertAlmostEqual(result["pass_at_1"], (2 / 3 + 2 / 3) / 2)
        self.assertEqual(result["attempts"], 6)
        self.assertEqual(result["short"], {})
        self.assertEqual(result["cost_per_attempt"], 1.0)

    def test_attempts_flag_sets_slots_for_one_attempt_jobs(self):
        t = self.tree
        for slot, fields in enumerate((GRADED, FAILED, GRADED)):
            t.job("deepswe", "modal", f"20261007T00000{slot}Z", 1, ("a", fields))
        self.assertAlmostEqual(t.score("deepswe")["pass_at_1"], 1.0)  # inferred one slot
        self.assertAlmostEqual(t.score("deepswe", attempts=3)["pass_at_1"], 2 / 3)

    def test_timeouts_and_blocks_score_zero_and_are_not_rerun(self):
        t = self.tree
        t.job("deepswe", "e2b", "20261007T000000Z", 3,
              ("a", {"reward": 1.0, "error": "AgentTimeoutError"}), ("a", {"error": "VerifierTimeoutError"}),
              ("a", {"error": "ReasonSessionTerminalError", "message": "Session failed: instruction_blocked"}))
        t.job("deepswe", "e2b", "20261007T010000Z", 3, ("a", GRADED), ("a", GRADED), ("a", GRADED))
        result = t.score("deepswe")
        self.assertEqual(result["pass_at_1"], 0.0)
        self.assertEqual(result["short"], {})

    def test_refusals_are_redrawn_ten_times_then_score_zero(self):
        t = self.tree
        t.job("swe-atlas-qna", "e2b", "20261006T000000Z", 3, ("a", GRADED), ("a", REFUSED), ("a", REFUSED),
              ("b", GRADED), ("b", GRADED), ("b", GRADED))
        for rerun in range(1, 9):  # the second slot's draw and its first 9 redraws are refused
            t.job("swe-atlas-qna", "e2b", f"20261006T0{rerun}0000Z", 1, ("a", REFUSED))
        result = t.score("swe-atlas-qna")
        self.assertEqual(result["short"], {"a": 2})
        self.assertAlmostEqual(result["pass_at_1"], (1 / 3 + 1) / 2)
        # The tenth redraw is refused too: that slot scores 0, and the next draw fills the third.
        t.job("swe-atlas-qna", "e2b", "20261006T090000Z", 1, ("a", REFUSED))
        t.job("swe-atlas-qna", "e2b", "20261006T100000Z", 1, ("a", GRADED))
        result = t.score("swe-atlas-qna")
        self.assertEqual(result["short"], {})
        self.assertAlmostEqual(result["pass_at_1"], (2 / 3 + 1) / 2)

    def test_adjudications_void_a_job_and_mark_refusals(self):
        t = self.tree
        bad = t.job("terminal-bench", "e2b", "20261007T000000Z", 3, ("a", FAILED), ("a", FAILED), ("a", FAILED))
        t.job("terminal-bench", "e2b", "20261007T100000Z", 3, ("a", GRADED), ("a", GRADED), ("a", FAILED))
        refused = t.job("terminal-bench", "e2b", "20261007T110000Z", 1, ("b", ERROR))
        trial = next(p for p in refused.iterdir() if p.is_dir())
        (t.root / "adjudications.json").write_text(json.dumps({
            "void": {str(bad.relative_to(t.root)): "image ENV missing on e2b (adapter 0.3.15)"},
            "refused": {str(trial.relative_to(t.root)): "OpenAI cyber filter"}}))
        result = t.score("terminal-bench")
        self.assertAlmostEqual(result["pass_at_1"], (2 / 3 + 0) / 2)
        self.assertEqual(result["short"], {"b": 3})

    def test_screened_judge_failures_score_zero(self):
        t = self.tree
        t.job("terminal-bench", "e2b", "20261007T000000Z", 2, ("a", GRADED), ("a", GRADED))
        result = t.score("terminal-bench", failed={"20261007T000000Z-1"})
        self.assertEqual((result["pass_at_1"], result["screened"]), (1.0, 0.5))
        self.assertEqual((result["ci95"], result["ci95_screened"]), ((1.0, 1.0), (0.5, 0.5)))

    def main(self, *args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            status = score.main(self.tree.root, *args)
        return status, out.getvalue(), err.getvalue()

    def test_main_prints_the_table(self):
        t = self.tree
        for bench in score.EXPECTED_TASKS:
            t.job(bench, "e2b", "20261007T000000Z", 1, ("a", GRADED))
        self.assertIn("| **Index** | | **100.0** | 100.0–100.0 | | | | | |", self.main()[1])
        (t.root / "screening.json").write_text(json.dumps({"trials": {}}))
        table, builds = self.main()[1].split("\n\n", 1)
        lines = table.splitlines()
        self.assertEqual(lines[0], "| Benchmark | Jobs | Pass@1 | 95% CI | Screened | Screened 95% CI "
                                   "| Attempt spread | Cost / attempt | Agent time | Tasks | Attempts |")
        self.assertTrue(all(line.count("|") == lines[0].count("|") for line in lines))
        self.assertIn("| adapter | 0.3.16 (3) |", builds)

    def test_spread_cost_coverage_and_agent_time(self):
        t = self.tree
        t.job("deepswe", "e2b", "20261007T000000Z", 2, ("a", {"reward": 1.0, "cost": None, "minutes": 30}),
              ("a", {"reward": 0.0, "minutes": 10}), ("b", {"reward": 1.0, "minutes": 20}), ("b", {"reward": 1.0}))
        result = t.score("deepswe")
        self.assertEqual(result["attempt_spread"], (0.5, 1.0))  # first attempts 2/2, second attempts 1/2
        self.assertEqual((result["costed_attempts"], result["counted_attempts"]), (3, 4))
        self.assertEqual(result["agent_minutes"], 15)

    def test_cost_prices_each_response_and_the_subagents(self):
        subagent = usage(response(prompt=10_000, cached=0, written=0, output=100))
        # Astra: $10 / $1 / $12.50 / $50 per million; over 272k input, $20 / $2 / $25 / $75.
        priced = usage(response(prompt=100_000, cached=90_000, written=5_000, output=1_000),
                       response(prompt=300_000, cached=299_000, written=0, output=0), subagents=[subagent])
        priced["final_metrics"]["extra"] = {"session_totals": dict(priced["final_metrics"])}
        self.tree.job("deepswe", "e2b", "20261007T000000Z", 1, ("a", {"reward": 1.0, "trajectory": priced}))
        result = self.tree.score("deepswe")
        uncached, read, written, output = result["cost_by_kind"]
        self.assertAlmostEqual(uncached, 0.05 + 0.02 + 0.1)
        self.assertAlmostEqual(read, 0.09 + 0.598)
        self.assertAlmostEqual(written, 0.0625)
        self.assertAlmostEqual(output, 0.05 + 0.005)
        self.assertAlmostEqual(result["cost_per_attempt"], 0.9755)  # not the reported $1.00
        self.assertEqual(result["reported_cost_attempts"], 0)
        self.assertEqual(score.priced(priced)[1], "complete")

    def test_cost_falls_back_to_the_reported_cost_when_usage_is_incomplete(self):
        short = usage(response(), totals={"total_prompt_tokens": 5_000})  # responses missing from the export
        unpriced = usage(response(), model="openai/gpt-9")
        broken_subagent = usage(response(), subagents=[short])
        for exported, problem in ((short, "incomplete"), (unpriced, "no price for gpt-9"), (broken_subagent, "incomplete")):
            self.assertEqual(score.priced(exported), (None, problem))
        self.assertEqual(score.priced({"steps": [{"source": "agent"}]}), (None, None))  # an older export
        self.tree.job("deepswe", "e2b", "20261007T000000Z", 1, ("a", {"reward": 1.0, "trajectory": short}),
                      ("b", {"reward": 1.0, "cost": 3.0}))
        result = self.tree.score("deepswe")
        self.assertEqual((result["cost_per_attempt"], result["reported_cost_attempts"]), (2.0, 2))
        status, out, err = self.main(None, True)
        self.assertIn("$2.000 (2 reported)", out)
        self.assertIn("| token usage | 2: incomplete (1), unknown (1) |", out)
        self.assertIn("1 counted attempts have token usage: incomplete", err)

    def test_index_interval_resamples_every_benchmark(self):
        means = [1.0, 0.0, 1.0, 0.0]
        self.assertEqual(score.ci95(means), score.ci95(means))  # deterministic
        low, high = score.ci95(means, [1.0] * 4, [0.0] * 4)
        self.assertTrue(1 / 3 <= low < 0.5 < high <= 2 / 3)  # the other two benchmarks hold it to 1/3–2/3

    def test_strict_needs_a_complete_run_on_one_configuration(self):
        t = self.tree
        for bench in score.EXPECTED_TASKS:
            t.job(bench, "e2b", "20261007T000000Z", 1, ("a", GRADED))
        status, _, err = self.main(None, True)
        self.assertEqual(status, 1)
        self.assertIn("deepswe has results for 1 of 113 tasks", err)
        self.assertNotIn("mix", err)
        # Server commits and environments may differ; the adapter may not.
        t.job("deepswe", "modal", "20261007T000001Z", 1, ("b", {"reward": 1.0, "commit": "d" * 40}),
              ("c", {"reward": 1.0, "adapter": "0.3.9"}))
        status, out, err = self.main(None, True)
        self.assertIn("counted attempts mix 2 values of adapter", err)
        self.assertNotIn("server commit", err)
        self.assertIn("| server commit | 2: cccccccccc (4), dddddddddd (1) |", out)

    def test_strict_gates_each_trajectory_on_one_build_and_full_fidelity(self):
        t = self.tree
        t.job("deepswe", "e2b", "20261007T000000Z", 1,
              ("a", {"reward": 1.0, "trajectory": trajectory()}),
              ("b", {"reward": 1.0, "trajectory": trajectory(commits=("c" * 40, "d" * 40))}),
              ("c", {"reward": 1.0, "trajectory": trajectory(without_build=2)}),
              ("d", {"reward": 1.0, "trajectory": trajectory(excerpts=1)}),
              ("e", {"reward": 1.0, "trajectory": trajectory(redactions={"[redacted-secret]": 1, "[redacted]": 1})}),
              ("f", {"reward": 1.0, "trajectory": trajectory(redactions={"[redacted-secret]": 3, "[redacted-run-token]": 1, "[redacted-token]": 0})}))
        status, out, err = self.main(None, True)
        self.assertEqual(status, 1)
        self.assertIn("| build per step | 2: one (4), spans builds (2) |", out)
        self.assertIn("2 counted attempts have build per step: spans builds", err)
        self.assertIn("1 counted attempts have trajectory fidelity: excerpts", err)
        self.assertIn("1 counted attempts have trajectory fidelity: masks [redacted]", err)
        self.assertNotIn("don't record", err)
        listed = next(line for line in err.splitlines() if line.startswith("deepswe counted attempts with build per step"))
        self.assertEqual(sorted(path.split("/")[-1].split("__")[0] for path in listed.split(": ", 2)[2].split()), ["b", "c"])

    def test_strict_requires_one_harness_digest(self):
        t = self.tree
        t.job("deepswe", "e2b", "20261007T000000Z", 1, ("a", {"reward": 1.0, "trajectory": trajectory()}),
              ("b", {"reward": 1.0, "trajectory": trajectory(digest="sha256:bbb")}))
        status, out, err = self.main(None, True)
        self.assertIn("| harness digest | 2: sha256:aaa (1), sha256:bbb (1) |", out)
        self.assertIn("counted attempts mix 2 values of harness digest", err)

    def test_older_trajectories_score_as_before_and_fail_strict_as_unknown(self):
        t = self.tree
        old = {"agent": {"name": "reason", "extra": {"commit_sha": "c" * 40}},
               "extra": {"fidelity": {"redaction_markers": {}, "excerpt_tool_events": 0}}}
        t.job("deepswe", "e2b", "20261007T000000Z", 1, ("a", {"reward": 1.0, "trajectory": old}),
              ("b", {"reward": 0.0}), ("c", {"reward": 1.0, "trajectory": trajectory(commits=None)}))
        self.assertAlmostEqual(t.score("deepswe")["pass_at_1"], 2 / 3)
        status, out, err = self.main()
        self.assertEqual(status, 0)
        self.assertIn("| build per step | unknown (3) |", out)
        self.assertIn("| trajectory fidelity | 2: unknown (2), complete (1) |", out)
        self.assertIn("deepswe counted attempts with build per step: unknown: ", err)
        status, _, err = self.main(None, True)
        self.assertIn("3 counted attempts don't record their build per step", err)
        self.assertIn("2 counted attempts don't record their trajectory fidelity", err)
        self.assertIn("2 counted attempts don't record their harness digest", err)

    def test_expect_lists_tasks_off_the_preflight_value(self):
        t = self.tree
        t.job("terminal-bench", "e2b", "20261007T000000Z", 1, ("a", GRADED), ("b", FAILED))
        self.assertEqual(self.main(None, False, 1.0)[0], 1)
        self.assertIn("1 differ: terminal-bench/b(0.00)", self.main(None, False, 1.0)[2])
        self.assertIn("terminal-bench/a(1.00)", self.main(None, False, 0.0)[2])
        # A nop preflight where every task that ran scored 0 still fails if tasks didn't run.
        t.job("deepswe", "e2b", "20261007T000001Z", 1, ("c", FAILED), ("d", ERROR))
        status, _, err = self.main(None, False, 0.0)
        self.assertIn("deepswe has results for 2 of 113 tasks; deepswe has 1 empty slots", err)
        self.assertIn("swe-atlas-qna has no results", err)

    def test_a_whole_run_folder_warns_that_part_jobs_are_ignored(self):
        t = self.tree
        t.job("deepswe", "all", "20261007T000000Z", 1, ("a", GRADED))
        t.job("deepswe", "e2b", "20261007T000001Z", 1, ("b", GRADED))
        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            self.assertEqual(len(score.jobs_for(t.root / "deepswe")), 1)
        self.assertIn("1 part jobs are ignored", err.getvalue())


if __name__ == "__main__":
    unittest.main()
