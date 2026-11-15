"""nodus_environment.py against a local stand-in for a Nodus Sandbox.

Needs Harbor and the Nodus SDK (Harbor's tool environment), so CI skips it:
  ~/.local/share/uv/tools/harbor/bin/python -m unittest tests.test_nodus_environment
"""
import asyncio
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    import nodus  # noqa: F401
    from harbor.models.task.config import EnvironmentConfig, NetworkMode, NetworkPolicy
    from harbor.models.trial.paths import TrialPaths

    import nodus_environment as ne
except ImportError:  # pragma: no cover - CI has neither Harbor nor the Nodus SDK
    ne = None

VERIFIER_DOCKERFILE = """\
FROM public.ecr.aws/d3j8x8q7/swe-bench-202605:kh7brwh7cv23ggeshkz85ac5fx831x5k-v1.1

COPY test.sh /tests/test.sh
COPY grader.py /tests/grader.py
RUN chmod +x /tests/test.sh
"""


class _Stream:
    def __init__(self, data: bytes):
        self._data = data

    async def read_bytes(self) -> bytes:
        return self._data


class _Process:
    def __init__(self, completed):
        self.stdout, self.stderr, self._code = _Stream(completed.stdout), _Stream(completed.stderr), completed.returncode

    async def wait(self) -> int:
        return self._code


class _Files:
    async def read(self, path: str) -> bytes:
        return Path(path).read_bytes()

    async def write(self, path: str, data: bytes) -> None:
        Path(path).write_bytes(data)


class FakeSandbox:
    """Runs commands on this machine, as a Sandbox would run them in its container."""

    name = "fake"

    def __init__(self):
        self.files = _Files()
        self.calls = []

    async def exec(self, *argv, env=None, workdir=None, timeout=None):
        self.calls.append((argv, workdir, timeout))
        completed = subprocess.run(list(argv), cwd=workdir, env=env, capture_output=True)
        return _Process(completed)

    async def terminate(self):
        pass


@unittest.skipIf(ne is None, "needs Harbor and nodus-compute")
class NodusEnvironmentTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        (self.tmp / "env").mkdir()
        (self.tmp / "env" / "Dockerfile").write_text(VERIFIER_DOCKERFILE)

    def make(self, policy=None, phases=(), **kwargs):
        return ne.NodusEnvironment(
            self.tmp / "env", "igel", "igel__abc__verifier__grade", TrialPaths(self.tmp / "trial"),
            EnvironmentConfig(cpus=2, memory_mb=8192), network_policy=policy,
            phase_network_policies=list(phases), **kwargs)

    def test_replay_plan_of_a_deepswe_verifier(self):
        base, steps = ne.replay_plan(self.tmp / "env" / "Dockerfile")
        self.assertTrue(base.startswith("public.ecr.aws/d3j8x8q7/swe-bench-202605:"))
        self.assertEqual([s[0] for s in steps], ["COPY", "COPY", "RUN"])

    def test_replay_refuses_what_it_cannot_reproduce(self):
        for text in ("FROM a AS b\nFROM c\n", "FROM a\nCOPY --from=b /x /y\n", "FROM a\nUSER app\n"):
            (self.tmp / "env" / "Dockerfile").write_text(text)
            with self.assertRaises(ne.DockerfileReplayError, msg=text):
                ne.replay_plan(self.tmp / "env" / "Dockerfile")

    def test_sandbox_names_are_dns_labels(self):
        name = ne._sandbox_name("datacurve__igel-persist-feature-schema__AbC_12__verifier__grade" * 2)
        self.assertLessEqual(len(name), 63)
        self.assertRegex(name, r"^[a-z0-9][a-z0-9-]*[a-z0-9]$")

    def test_egress_is_the_most_open_phase(self):
        offline = NetworkPolicy(network_mode=NetworkMode.NO_NETWORK)
        agent = NetworkPolicy(network_mode=NetworkMode.ALLOWLIST, allowed_hosts=["api.reasonmachines.com"])
        self.assertEqual(self.make(offline)._egress()[1], "deny")
        egress, kind = self.make(offline, [agent])._egress()
        self.assertEqual(kind, "allowlist")
        self.assertEqual(egress.spec(), {"egress": {"policy": "AllowList", "allow": ["api.reasonmachines.com"]}})

    def test_exec_and_directory_round_trip(self):
        env = self.make()
        env._sandbox = FakeSandbox()
        result = asyncio.run(env.exec("echo out; echo err >&2; exit 3", cwd=str(self.tmp), timeout_sec=30))
        self.assertEqual((result.stdout, result.stderr, result.return_code), ("out\n", "err\n", 3))
        self.assertEqual(env._sandbox.calls[-1][2], "30s")

        source = self.tmp / "src"
        (source / "sub").mkdir(parents=True)
        (source / "a.txt").write_text("a")
        (source / "sub" / "b.bin").write_bytes(bytes(range(256)))
        asyncio.run(env.upload_dir(source, str(self.tmp / "remote")))
        asyncio.run(env.download_dir(str(self.tmp / "remote"), self.tmp / "back"))
        self.assertEqual((self.tmp / "back" / "a.txt").read_text(), "a")
        self.assertEqual((self.tmp / "back" / "sub" / "b.bin").read_bytes(), bytes(range(256)))
        self.assertTrue(asyncio.run(env.is_dir(str(self.tmp / "remote" / "sub"))))
        self.assertTrue(asyncio.run(env.is_file(str(self.tmp / "remote" / "a.txt"))))

    def test_replay_copies_from_the_build_context(self):
        env = self.make()
        env._sandbox = FakeSandbox()
        (self.tmp / "env" / "test.sh").write_text("#!/bin/sh\necho graded\n")
        target = self.tmp / "tests"
        asyncio.run(env._replay([("COPY", f"test.sh {target}/test.sh"), ("RUN", f"chmod +x {target}/test.sh")]))
        self.assertEqual(subprocess.run([str(target / "test.sh")], capture_output=True, text=True).stdout, "graded\n")


if __name__ == "__main__":
    unittest.main()
