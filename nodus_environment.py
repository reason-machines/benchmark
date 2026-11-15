"""Harbor environment that runs each trial in a Nodus Sandbox (https://www.nodus-compute.ai).

Use it with `HARBOR_ENV=nodus ./run.sh deepswe`, or directly:

    PYTHONPATH=. harbor run ... --env nodus_environment:NodusEnvironment

It needs `NODUS_API_KEY` and the Nodus SDK in Harbor's tool environment
(`uv tool install ... --with nodus-compute`).

What Nodus does differently from e2b, and how this environment handles it:

- A Sandbox starts from a published image and cannot build a Dockerfile. A task
  that pins `docker_image` starts from it. Otherwise the Dockerfile is replayed:
  the Sandbox starts from its FROM image and its WORKDIR, ENV, COPY/ADD and RUN
  steps run inside it. That covers DeepSWE's separate verifier image (the task
  image plus the hidden tests); anything else (multi-stage builds, COPY --from,
  USER) is refused rather than approximated.
- Commands run as the image's user without Linux capabilities, and every command
  is a recorded Process with its own timeout (10 minutes by default), so each
  exec passes its own timeout, or the Sandbox lifetime when Harbor gives none.
- The image's ENV is applied explicitly at creation (as the Reason e2b
  environment does), so the agent, its shells and the verifier see the task's
  PATH, virtualenv and toolchain.
- Egress is Deny or Open; the Python SDK does not send an allow-list yet. A
  phase that needs an allow-list (an offline DeepSWE task with the Reason API
  and relay opened for the agent) is first tried as a native AllowList; if the
  API refuses it, it fails unless `unenforced_allowlist=open` is passed, which
  runs the Sandbox with open egress and records that in the trial log. A run
  made that way does not meet the methodology's "tasks run without internet".
  The verifier's separate Sandbox stays Deny.
- Idle stop is turned off (`idleTimeout: 0s`): the Reason worker runs as a
  background process while Harbor only polls the Reason API, and a stop would
  kill it. `maxLifetime` and `maxCostUSD` bound every Sandbox instead.
"""
from __future__ import annotations

import asyncio
import io
import os
import posixpath
import re
import shlex
import tarfile
from pathlib import Path

from harbor.environments.base import BaseEnvironment, ExecResult
from harbor.environments.capabilities import (
    EnvironmentCapabilities,
    EnvironmentResourceCapabilities,
)
from harbor.environments.definition import effective_exec_cwd, parse_dockerfile_workdir
from harbor.models.task.config import NetworkMode, NetworkPolicy

# Nodus Sandbox resource and lifetime defaults; every one can be set with --ek.
DEFAULT_LIFETIME_SEC = 4 * 3600
DEFAULT_MAX_COST_USD = 5
DEFAULT_DISK_GIB = 20
SANDBOX_NAME_LEN = 63


def _truthy(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on", "open"}


def _sandbox_name(session_id: str) -> str:
    """A DNS-label name from Harbor's session id, unique per trial."""
    name = re.sub(r"[^a-z0-9-]+", "-", session_id.lower()).strip("-")
    if len(name) > SANDBOX_NAME_LEN:
        import hashlib

        digest = hashlib.sha256(session_id.encode()).hexdigest()[:8]
        name = name[: SANDBOX_NAME_LEN - 9].rstrip("-") + "-" + digest
    return name or "harbor"


class DockerfileReplayError(RuntimeError):
    """The Dockerfile needs a build step a Nodus Sandbox cannot replay."""


def replay_plan(dockerfile: Path) -> tuple[str, list[tuple[str, str]]]:
    """(base image, [(instruction, value)]) for a single-stage Dockerfile, or raise."""
    from dockerfile_parse import DockerfileParser

    parser = DockerfileParser(path=str(dockerfile))
    base, steps, seen_from = None, [], False
    for item in parser.structure:
        instruction, value = item["instruction"].upper(), item["value"].strip()
        if instruction == "FROM":
            if seen_from:
                raise DockerfileReplayError("multi-stage Dockerfiles cannot be replayed on Nodus")
            seen_from = True
            parts = value.split()
            if any(p.startswith("--") for p in parts) or len(parts) != 1:
                raise DockerfileReplayError(f"unsupported FROM: {value}")
            base = parts[0]
        elif instruction in {"RUN", "ENV", "WORKDIR", "COPY", "ADD"}:
            if instruction in {"COPY", "ADD"} and any(
                p.startswith("--from") for p in shlex.split(value)
            ):
                raise DockerfileReplayError(f"{instruction} --from cannot be replayed on Nodus")
            steps.append((instruction, value))
        elif instruction in {"CMD", "ENTRYPOINT", "LABEL", "EXPOSE", "COMMENT", "ARG", "STOPSIGNAL", "HEALTHCHECK", "SHELL"}:
            if instruction == "ARG" and steps:
                raise DockerfileReplayError("ARG after the first build step is not replayed")
            continue
        else:
            raise DockerfileReplayError(f"{instruction} cannot be replayed on Nodus")
    if not base:
        raise DockerfileReplayError("Dockerfile has no FROM")
    return base, steps


class NodusEnvironment(BaseEnvironment):
    """One Nodus Sandbox per Harbor environment (the agent's, and a separate verifier's)."""

    @classmethod
    def preflight(cls) -> None:
        if not os.environ.get("NODUS_API_KEY"):
            raise SystemExit("Nodus requires NODUS_API_KEY to be set.")
        try:
            import nodus  # noqa: F401
        except ImportError:
            raise SystemExit(
                "Install the Nodus SDK into Harbor's environment: "
                'uv tool install "harbor[e2b,modal]==0.22.0" --with "reason-machines-harbor>=0.3.44" --with nodus-compute'
            ) from None

    def __init__(self, environment_dir, environment_name, session_id, trial_paths, task_env_config, *args,
                 unenforced_allowlist: str | None = None, lifetime_sec: int | str | None = None,
                 max_cost_usd: float | str | None = None, disk_gib: int | str | None = None,
                 regions: str | None = None, **kwargs):
        # Capabilities are read during super().__init__, so set what they depend on first.
        self._unenforced_allowlist = _truthy(unenforced_allowlist) if unenforced_allowlist is not None else False
        super().__init__(environment_dir=environment_dir, environment_name=environment_name,
                         session_id=session_id, trial_paths=trial_paths,
                         task_env_config=task_env_config, **kwargs)
        self._lifetime_sec = int(lifetime_sec or DEFAULT_LIFETIME_SEC)
        self._max_cost_usd = float(max_cost_usd or DEFAULT_MAX_COST_USD)
        self._disk_gib = int(disk_gib or 0) or None
        self._regions = [r for r in (regions or "").split(",") if r] or None
        self._sandbox = None
        self._image_env: dict[str, str] = {}
        self._dockerfile = self.environment_dir / "Dockerfile"
        self._workdir = parse_dockerfile_workdir(self._dockerfile) if self._dockerfile.exists() else None
        self.egress_used: str | None = None

    @staticmethod
    def type() -> str:
        return "nodus"

    @classmethod
    def resource_capabilities(cls) -> EnvironmentResourceCapabilities:
        return EnvironmentResourceCapabilities(cpu_request=True, memory_request=True)

    @property
    def capabilities(self) -> EnvironmentCapabilities:
        # disable_internet is real (Deny). The allow-list is native when the API takes it,
        # and otherwise open egress, only when the run opted in with unenforced_allowlist.
        return EnvironmentCapabilities(
            disable_internet=True,
            network_allowlist=True,
            network_allowlist_hostnames=True,
            network_allowlist_wildcard_hostnames=True,
            dynamic_network_policy=True,
        )

    def _validate_definition(self):
        if not self.task_env_config.docker_image and not (self.environment_dir / "Dockerfile").exists():
            raise FileNotFoundError(
                f"Nodus needs a docker_image or a Dockerfile in {self.environment_dir}")

    # ----- creation -------------------------------------------------------

    def _policies(self) -> list[NetworkPolicy]:
        return [self.network_policy, *self._phase_network_policies]

    def _egress(self):
        """The one egress policy the Sandbox is created with: the most open its phases need."""
        import nodus

        modes = {p.network_mode for p in self._policies()}
        if NetworkMode.PUBLIC in modes:
            return nodus.Egress.open(), "open"
        if NetworkMode.ALLOWLIST in modes:
            hosts = sorted({h for p in self._policies() for h in (p.allowed_hosts or [])})
            return nodus.Egress.allow(*hosts), "allowlist"
        return nodus.Egress.deny(), "deny"

    async def _create(self, image: str, egress) -> None:
        from nodus import errors
        from nodus.api._client import default_client
        from nodus.sandbox import _Sandbox, _sandbox_spec

        cpus = self._effective_cpus or 2
        memory_mb = self._effective_memory_mb or 4096
        disk_gib = self._disk_gib or max(DEFAULT_DISK_GIB, -(-(self._effective_storage_mb or 0) // 1024))
        client = default_client()
        project = await client.project(None)
        spec = await _sandbox_spec(
            client, project, (), image=image, image_pull_secrets=None, cpu=cpus, memory=f"{memory_mb}Mi",
            gpu=None, fuse_mount=None, disk=f"{disk_gib}Gi", timeout=f"{self._lifetime_sec}s",
            idle_timeout="0s", on_idle=None, secrets=None, volumes=None,
            env={**self._image_env, **self._startup_env()} or None, workdir=self._workdir, network=None,
            regions=self._regions, ports=None, init=None, service=None, max_cost=self._max_cost_usd,
        )
        # The SDK refuses an allow-list before sending it; send the spec ourselves so the API decides.
        spec["network"] = egress.spec()
        spec["startup"] = {"defaults": "Interactive"}
        meta = {"name": _sandbox_name(self.session_id),
                "labels": {"app": "harbor", "environment": re.sub(r"[^a-z0-9-]+", "-", self.environment_name.lower())[:63]}}
        try:
            obj = await client.create({"kind": "Sandbox", "metadata": meta, "spec": spec}, None, project=project)
        except (errors.Invalid, errors.Unsupported) as error:
            if egress.policy != "AllowList":
                raise
            if not self._unenforced_allowlist:
                raise RuntimeError(
                    "Nodus refused a Sandbox egress allow-list "
                    f"({type(error).__name__}: {error}). Pass --ek unenforced_allowlist=open to run "
                    "allow-listed phases with open egress (not network-isolated)."
                ) from error
            self.logger.warning("Nodus has no egress allow-list (%s); running %s with OPEN egress",
                                type(error).__name__, meta["name"])
            spec["network"] = {"egress": {"policy": "Open"}}
            obj = await client.create({"kind": "Sandbox", "metadata": meta, "spec": spec}, None, project=project)
            self.egress_used = "open (allow-list unenforced)"
        else:
            self.egress_used = egress.policy.lower()
        self._sandbox = _Sandbox(obj)
        self.logger.info("Nodus Sandbox %s: image=%s egress=%s cpu=%s memory=%sMi",
                         self._sandbox.name, image, self.egress_used, cpus, memory_mb)

    async def start(self, force_build: bool):
        from reasonmachines_harbor.image_runtime import image_runtime

        if self.task_env_config.docker_image:
            image, steps = self.task_env_config.docker_image, []
        else:
            image, steps = replay_plan(self._dockerfile)
        # The image's ENV under task and trial values (the Dockerfile's own ENV for a replay).
        self._image_env, image_workdir = await asyncio.to_thread(image_runtime, self)
        self._workdir = self._workdir or image_workdir
        egress, _ = self._egress()
        await self._create(image, egress)
        # A command waits for the Sandbox to start; the first one fails fast if the image can't run.
        probe = await self.exec("true", timeout_sec=900)
        if probe.return_code != 0:
            raise RuntimeError(f"Nodus Sandbox did not start: {probe.stderr or probe.stdout}")
        await self._replay(steps)
        await self.ensure_dirs(self._mount_targets(writable_only=True))
        await self._upload_environment_dir_after_start()

    async def _replay(self, steps: list[tuple[str, str]]) -> None:
        workdir = self._workdir or "/"
        for instruction, value in steps:
            if instruction == "WORKDIR":
                workdir = posixpath.join(workdir, value)
                await self._checked(f"mkdir -p {shlex.quote(workdir)}")
            elif instruction == "ENV":
                continue  # already in the Sandbox's env via image_runtime
            elif instruction == "RUN":
                await self._checked(value, cwd=workdir, timeout_sec=self.task_env_config.build_timeout_sec)
            else:  # COPY / ADD from the build context
                parts = [p for p in shlex.split(value) if not p.startswith("--")]
                *sources, target = parts
                if not target.startswith("/"):
                    target = posixpath.join(workdir, target)
                for source in sources:
                    local = (self.environment_dir / source).resolve()
                    if self.environment_dir.resolve() not in (local, *local.parents):
                        raise DockerfileReplayError(f"{instruction} source outside the context: {source}")
                    if local.is_dir():
                        await self.upload_dir(local, target.rstrip("/") or "/")
                    else:
                        dest = posixpath.join(target, local.name) if target.endswith("/") or len(sources) > 1 else target
                        await self.upload_file(local, dest)

    async def _checked(self, command: str, **kwargs) -> ExecResult:
        result = await self.exec(command, **kwargs)
        if result.return_code != 0:
            raise RuntimeError(f"Nodus replay step failed ({result.return_code}): {command}\n"
                               f"{(result.stderr or result.stdout or '')[-2000:]}")
        return result

    async def _apply_network_policy(self, network_policy: NetworkPolicy) -> None:
        # The Sandbox keeps the egress it was created with, the most open any phase needs.
        self.logger.debug("Nodus Sandbox keeps egress=%s for phase policy %s",
                          self.egress_used, network_policy.network_mode)

    async def stop(self, delete: bool):
        if self._sandbox is None:
            return
        try:
            await self._sandbox.terminate()
        except Exception as error:
            self.logger.error(f"Error terminating Nodus Sandbox {self._sandbox.name}: {error}")
        finally:
            self._sandbox = None

    # ----- commands -------------------------------------------------------

    def _require(self):
        if self._sandbox is None:
            raise RuntimeError("Sandbox not found. Please start the environment first.")
        return self._sandbox

    async def exec(self, command: str, cwd: str | None = None, env: dict[str, str] | None = None,
                   timeout_sec: int | None = None, user: str | int | None = None) -> ExecResult:
        sandbox = self._require()
        user = self._resolve_user(user)
        if user not in (None, "root", 0, "0"):
            self.logger.debug("Nodus runs commands as the image's user; ignoring user=%s", user)
        env = self._merge_env(env)
        workdir = effective_exec_cwd(cwd, self.task_env_config.workdir, self._workdir)
        timeout = int(timeout_sec) if timeout_sec else self._lifetime_sec
        process = await sandbox.exec("/bin/bash", "-c", command, env=env or None, workdir=workdir,
                                     timeout=f"{timeout}s")
        stdout, stderr = await asyncio.gather(process.stdout.read_bytes(), process.stderr.read_bytes())
        code = await process.wait()
        return ExecResult(stdout=stdout.decode(errors="replace"), stderr=stderr.decode(errors="replace"),
                          return_code=code)

    # ----- files ----------------------------------------------------------

    async def upload_file(self, source_path: Path | str, target_path: str):
        sandbox = self._require()
        parent = posixpath.dirname(target_path)
        if parent:
            await self._checked(f"mkdir -p {shlex.quote(parent)}", cwd="/")
        await sandbox.files.write(target_path, Path(source_path).read_bytes())

    async def upload_dir(self, source_dir: Path | str, target_dir: str):
        sandbox = self._require()
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
            for path in sorted(Path(source_dir).rglob("*")):
                archive.add(path, arcname=path.relative_to(source_dir).as_posix(), recursive=False)
        staging = f"/tmp/.harbor-upload-{os.urandom(6).hex()}.tgz"
        await sandbox.files.write(staging, buffer.getvalue())
        await self._checked(f"mkdir -p {shlex.quote(target_dir)} && tar -xzf {staging} -C {shlex.quote(target_dir)} "
                            f"--no-same-owner && rm -f {staging}", cwd="/")

    async def download_file(self, source_path: str, target_path: Path | str):
        sandbox = self._require()
        Path(target_path).parent.mkdir(parents=True, exist_ok=True)
        Path(target_path).write_bytes(await sandbox.files.read(source_path))

    async def download_dir(self, source_dir: str, target_dir: Path | str):
        sandbox = self._require()
        staging = f"/tmp/.harbor-download-{os.urandom(6).hex()}.tgz"
        result = await self.exec(f"[ -d {shlex.quote(source_dir)} ] && tar -czf {staging} -C {shlex.quote(source_dir)} .",
                                 cwd="/", timeout_sec=600)
        if result.return_code != 0:
            raise FileNotFoundError(f"{source_dir} could not be archived in the Sandbox: {result.stderr}")
        try:
            data = await sandbox.files.read(staging)
        finally:
            await self.exec(f"rm -f {staging}", cwd="/", timeout_sec=60)
        target = Path(target_dir)
        target.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            archive.extractall(target, filter="data")

    async def is_dir(self, path: str, user: str | int | None = None) -> bool:
        return (await self.exec(f"test -d {shlex.quote(path)}", cwd="/", timeout_sec=60)).return_code == 0

    async def is_file(self, path: str, user: str | int | None = None) -> bool:
        return (await self.exec(f"test -f {shlex.quote(path)}", cwd="/", timeout_sec=60)).return_code == 0
