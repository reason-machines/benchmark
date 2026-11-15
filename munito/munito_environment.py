"""Harbor environment on munito.ai sandboxes (prototype).

munito.ai sandboxes are Linux microVMs started from a fixed set of templates
(base, ubuntu, agent, desktop); there is no custom-image template like E2B's.
So this environment runs the task the way Harbor already runs compose tasks on
Daytona, Modal and GKE: one microVM from the ``ubuntu`` template (Docker,
Compose and Buildx preinstalled and running), the task image pulled or built
inside it, and ``docker compose`` starting ``main`` plus any sidecars. Harbor's
shared ``DinDComposeOps`` does exec and file transfer on top of four
primitives implemented here with munito.ai's REST API.

Because the task runs as a container, Docker applies the image's ENV, WORKDIR
and user natively, so neither E2B's dropped-ENV workaround nor its exclusion
lists (multi-container tasks, images whose apt sources fail E2B's template
build) apply. GPUs are not offered (munito.ai keeps them for internal orgs).

Network policy is enforced in the VM, not by munito.ai (whose only control is
internet on or off, and the VM needs internet to pull the image). Every bridge
of the compose project gets a rule set in its own iptables chain under
DOCKER-USER: public returns, no-network drops traffic leaving the project's
bridges, and an allowlist accepts the resolved IPv4 addresses (and CIDRs)
first. Rewriting the chain switches policy at runtime, so Harbor's per-phase
policies work. Hostnames resolve once per switch; a CDN host that changes
addresses mid-run can drop out of the allowlist.

Credentials: MUNITO_API_KEY. Optional: MUNITO_API_BASE (default
https://api.munito.ai/sandboxes/v1).

Environment kwargs (``--ek``): template (ubuntu), disk_gib, sandbox_timeout_secs
(default 86400; at most 7200 during munito.ai's trial), vm_memory_headroom_mb
(1024), min_vcpus (2), docker_login (on when DOCKERHUB_USERNAME and
DOCKERHUB_TOKEN are set).

Run it with Harbor: ``--env munito_environment:MunitoEnvironment`` with this
folder on PYTHONPATH.
"""
from __future__ import annotations

import asyncio
import ipaddress
import json
import os
import shlex
import tempfile
import time
from pathlib import Path
from typing import Any, override
from uuid import uuid4

import httpx

from harbor.constants import MAIN_SERVICE_NAME
from harbor.environments.base import BaseEnvironment, ExecResult
from harbor.environments.capabilities import (
    EnvironmentCapabilities,
    EnvironmentResourceCapabilities,
)
from harbor.environments.compose_service_ops import (
    ComposeServiceOpsMixin,
    ComposeServiceTransport,
)
from harbor.environments.definition import should_use_prebuilt_docker_image
from harbor.environments.dind_compose import DinDComposeOps
from harbor.environments.docker import (
    COMPOSE_BUILD_PATH,
    COMPOSE_PREBUILT_PATH,
    ENV_COMPOSE_NAME,
    RESOURCES_COMPOSE_NAME,
    self_bind_mount,
    write_mounts_compose_file,
    write_resources_compose_file,
)
from harbor.environments.docker.compose_env import (
    ComposeInfraEnvVars,
    legacy_log_mount_env_vars,
    merge_compose_env,
)
from harbor.environments.docker.docker import _sanitize_docker_image_name
from harbor.environments.tar_transfer import (
    extract_dir_from_file,
    pack_dir_to_file,
    remote_pack_command,
    remote_unpack_command,
)
from harbor.models.task.config import (
    NetworkAllowlistEntryType,
    NetworkMode,
    NetworkPolicy,
    classify_network_allowlist_entry,
)
from harbor.models.trial.config import ResourceMode, ServiceVolumeConfig
from harbor.utils.env import resolve_env_vars

DEFAULT_API_BASE = "https://api.munito.ai/sandboxes/v1"
# munito.ai's synchronous exec stops a command at 1,800 s; longer (or unbounded)
# commands run as background commands and are polled.
SYNC_EXEC_MAX_SEC = 1_700
POLL_INTERVAL_SEC = 2.0
FILE_MAX_BYTES = 100 * 1024 * 1024
RETRYABLE_CODES = {"too_many_streams", "sandbox_unavailable", "no_capacity", "start_unknown"}


class MunitoApiError(RuntimeError):
    def __init__(self, status: int, code: str | None, detail: str):
        super().__init__(f"munito.ai API {status} {code or ''}: {detail}".strip())
        self.status, self.code = status, code


class MunitoClient:
    """A small async client for the munito.ai Sandboxes API, one per event loop."""

    _instances: dict[int, "MunitoClient"] = {}

    def __init__(self, api_key: str, base: str):
        self._base = base.rstrip("/")
        self._http = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=httpx.Timeout(120.0, connect=30.0),
            limits=httpx.Limits(max_connections=400, max_keepalive_connections=100),
        )

    @classmethod
    def get(cls) -> "MunitoClient":
        loop = id(asyncio.get_running_loop())
        if loop not in cls._instances:
            key = os.environ.get("MUNITO_API_KEY")
            if not key:
                raise RuntimeError("MUNITO_API_KEY is not set")
            cls._instances[loop] = cls(key, os.environ.get("MUNITO_API_BASE", DEFAULT_API_BASE))
        return cls._instances[loop]

    async def request(self, method: str, path: str, *, retries: int = 6,
                      timeout: float | None = None, headers: dict[str, str] | None = None,
                      **kwargs: Any) -> httpx.Response:
        delay = 1.0
        for attempt in range(retries + 1):
            try:
                response = await self._http.request(
                    method, self._base + path, headers=headers,
                    timeout=httpx.Timeout(timeout, connect=30.0) if timeout else httpx.USE_CLIENT_DEFAULT,
                    **kwargs,
                )
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
                # Nothing reached the API, so a replay cannot duplicate work.
                if attempt == retries:
                    raise
                await asyncio.sleep(delay)
                delay = min(delay * 2, 20)
                continue
            if response.status_code < 400:
                return response
            code, detail = None, response.text[:500]
            try:
                problem = response.json()
                code = problem.get("code")
                detail = problem.get("detail") or problem.get("title") or detail
            except ValueError:
                pass
            retry_after = response.headers.get("Retry-After", "")
            if attempt < retries and (code in RETRYABLE_CODES or response.status_code in (502, 503, 504)):
                await asyncio.sleep(float(retry_after) if retry_after.isdigit() else delay)
                delay = min(delay * 2, 20)
                continue
            raise MunitoApiError(response.status_code, code, detail)
        raise AssertionError("unreachable")


class _MunitoCompose(DinDComposeOps):
    """docker compose inside one munito.ai microVM (mirrors Harbor's Daytona DinD strategy)."""

    _SELF_BIND_LOG_DIRS = True
    _COMPOSE_DIR = "/harbor/compose"
    _ENVIRONMENT_DIR = "/harbor/environment"
    _MOUNTS_COMPOSE_NAME = "docker-compose-mounts.json"
    _CP_FILE_TIMEOUT_SEC = 120
    _CP_DIR_TIMEOUT_SEC = 300

    def __init__(self, env: "MunitoEnvironment"):
        self._env = env
        self._use_prebuilt = False
        self._resolved_task_env = (
            resolve_env_vars(env.task_env_config.env) if env.task_env_config.env else {}
        )

    # ── DinDComposeOps primitives ───────────────────────────────────────

    @override
    async def _host_exec(self, command: str, timeout_sec: int | None = None) -> ExecResult:
        return await self._env._vm_exec(command, timeout_sec=timeout_sec)

    @override
    async def _stage_file_to_host(self, source_path: Path | str, host_path: str):
        await self._env._put_file(Path(source_path).read_bytes(), host_path)

    @override
    async def _stage_dir_to_host(self, source_dir: Path | str, host_dir: str):
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "dir.tgz"
            pack_dir_to_file(source_dir, archive, compress=True)
            remote = f"/tmp/harbor_{uuid4().hex}.tgz"
            await self._env._put_file(archive.read_bytes(), remote)
        result = await self._env._vm_exec(
            f"{remote_unpack_command(remote, host_dir)}; rc=$?; rm -f {shlex.quote(remote)}; exit $rc",
            timeout_sec=300,
        )
        if result.return_code:
            raise RuntimeError(f"unpack into {host_dir} failed: {result.stderr or result.stdout}")

    @override
    async def _fetch_file_from_host(self, host_path: str, target_path: Path | str):
        Path(target_path).parent.mkdir(parents=True, exist_ok=True)
        Path(target_path).write_bytes(await self._env._get_file(host_path))

    @override
    async def _fetch_dir_from_host(self, host_dir: str, target_dir: Path | str):
        remote = f"/tmp/harbor_{uuid4().hex}.tgz"
        result = await self._env._vm_exec(remote_pack_command(host_dir, remote), timeout_sec=300)
        if result.return_code:
            raise RuntimeError(f"pack of {host_dir} failed: {result.stderr or result.stdout}")
        try:
            data = await self._env._get_file(remote)
        finally:
            await self._env._vm_exec(f"rm -f {shlex.quote(remote)}", timeout_sec=30)
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "dir.tgz"
            archive.write_bytes(data)
            Path(target_dir).mkdir(parents=True, exist_ok=True)
            extract_dir_from_file(archive, target_dir)

    # ── compose wiring ──────────────────────────────────────────────────

    @property
    def project_name(self) -> str:
        return self._env.session_id.lower().replace(".", "-")

    def _resolve_volumes(self) -> list[ServiceVolumeConfig]:
        # Trial's bind sources are local paths; inside the VM the source equals the target.
        return [self_bind_mount(m) if m.get("type") == "bind" else m for m in self._env._mounts]

    def _infra_env_vars(self) -> dict[str, str]:
        env = self._env
        values = ComposeInfraEnvVars(
            main_image_name=_sanitize_docker_image_name(f"hb__{env.environment_name}"),
            context_dir=self._ENVIRONMENT_DIR,
            prebuilt_image_name=env.task_env_config.docker_image if self._use_prebuilt else None,
            cpus=env._effective_cpus,
            memory=f"{mb}M" if (mb := env._effective_memory_mb) else None,
        ).to_env_dict()
        values.update(legacy_log_mount_env_vars(self._resolve_volumes(), host_value="target"))
        return values

    def _compose_env_vars(self) -> dict[str, str]:
        user_env = {**self._resolved_task_env, **(self._env._persistent_env or {})}
        return merge_compose_env(user_env=user_env, infra_env=self._infra_env_vars(),
                                 logger=self._env.logger)

    def _extra_compose_target_paths(self) -> list[str]:
        return [f"{self._COMPOSE_DIR}/docker-compose-extra-{i}.yaml"
                for i, _ in enumerate(self._env.extra_docker_compose_paths)]

    def _compose_file_flags(self) -> list[str]:
        files = [
            f"{self._COMPOSE_DIR}/{RESOURCES_COMPOSE_NAME}",
            f"{self._COMPOSE_DIR}/"
            + ("docker-compose-prebuilt.yaml" if self._use_prebuilt else "docker-compose-build.yaml"),
            f"{self._COMPOSE_DIR}/{self._MOUNTS_COMPOSE_NAME}",
        ]
        if (self._env.environment_dir / "docker-compose.yaml").exists():
            files.append(f"{self._ENVIRONMENT_DIR}/docker-compose.yaml")
        files.extend(self._extra_compose_target_paths())
        files.append(f"{self._COMPOSE_DIR}/{ENV_COMPOSE_NAME}")
        # No docker-compose-no-network.yaml: no-network is an iptables policy, so it
        # can switch at runtime like the other modes.
        return [flag for path in files for flag in ("-f", path)]

    def compose_cmd(self, subcommand: list[str]) -> str:
        return shlex.join(["docker", "compose", "-p", self.project_name,
                           "--project-directory", self._ENVIRONMENT_DIR,
                           *self._compose_file_flags(), *subcommand])

    @override
    async def _compose_exec(self, subcommand: list[str], timeout_sec: int | None = None) -> ExecResult:
        return await self._env._vm_exec(self.compose_cmd(subcommand), env=self._compose_env_vars(),
                                        timeout_sec=timeout_sec)

    async def _stage_resources_compose_file(self) -> None:
        env = self._env
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / RESOURCES_COMPOSE_NAME
            write_resources_compose_file(
                path,
                cpu_request=env._resource_request_value("cpu", auto_mode=ResourceMode.REQUEST),
                cpu_limit=env._resource_limit_value("cpu", auto_mode=ResourceMode.REQUEST),
                memory_request_mb=env._resource_request_value("memory", auto_mode=ResourceMode.REQUEST),
                memory_limit_mb=env._resource_limit_value("memory", auto_mode=ResourceMode.REQUEST),
            )
            if not path.exists():
                path.write_text("services: {}\n")
            await self._stage_file_to_host(path, f"{self._COMPOSE_DIR}/{RESOURCES_COMPOSE_NAME}")

    async def start(self, force_build: bool) -> None:
        env = self._env
        for path in (COMPOSE_BUILD_PATH, COMPOSE_PREBUILT_PATH):
            await self._stage_file_to_host(path, f"{self._COMPOSE_DIR}/{path.name}")
        await self._stage_resources_compose_file()
        await self._stage_env_compose_file(self._COMPOSE_DIR)
        await self._stage_dir_to_host(env.environment_dir, self._ENVIRONMENT_DIR)
        for source, target in zip(env.extra_docker_compose_paths,
                                  self._extra_compose_target_paths(), strict=True):
            await self._stage_file_to_host(source, target)
        volumes = self._resolve_volumes()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / self._MOUNTS_COMPOSE_NAME
            write_mounts_compose_file(path, volumes)
            await self._stage_file_to_host(path, f"{self._COMPOSE_DIR}/{self._MOUNTS_COMPOSE_NAME}")
        sources = [v["source"] for v in volumes if v.get("type") == "bind"]
        if sources:
            quoted = " ".join(shlex.quote(s) for s in sources)
            await env._vm_exec(f"mkdir -p {quoted} && chmod 777 {quoted}", timeout_sec=30)

        self._use_prebuilt = should_use_prebuilt_docker_image(
            env.environment_dir, docker_image=env.task_env_config.docker_image, force_build=force_build)
        build_timeout = round(env.task_env_config.build_timeout_sec)
        t0 = time.monotonic()
        if self._use_prebuilt:
            # Pull explicitly, so a slow registry shows up as image time rather than `up`.
            result = await self._compose_exec(["pull", "--quiet", MAIN_SERVICE_NAME], timeout_sec=build_timeout)
        else:
            result = await self._compose_exec(["build"], timeout_sec=build_timeout)
        if result.return_code:
            raise RuntimeError(f"docker compose {'pull' if self._use_prebuilt else 'build'} failed: "
                               f"{result.stdout[-2000:]} {result.stderr[-2000:]}")
        env.timings["image_s"] = round(time.monotonic() - t0, 2)
        t0 = time.monotonic()
        result = await self._compose_exec(["up", "-d"], timeout_sec=600)
        if result.return_code:
            raise RuntimeError(f"docker compose up failed: {result.stdout[-2000:]} {result.stderr[-2000:]}")
        for _ in range(60):
            probe = await self._compose_exec(["exec", "-T", MAIN_SERVICE_NAME, "true"], timeout_sec=20)
            if probe.return_code == 0:
                break
            await asyncio.sleep(1)
        else:
            raise RuntimeError("main container did not start")
        env.timings["up_s"] = round(time.monotonic() - t0, 2)


class MunitoEnvironment(ComposeServiceOpsMixin, BaseEnvironment):
    """A Harbor environment whose task containers run in a munito.ai microVM."""

    @classmethod
    @override
    def preflight(cls) -> None:
        if not os.environ.get("MUNITO_API_KEY"):
            raise SystemExit("munito.ai requires MUNITO_API_KEY to be set.")

    def __init__(self, *args, template: str = "ubuntu", disk_gib: int | None = None,
                 sandbox_timeout_secs: int = 86_400, vm_memory_headroom_mb: int = 1024,
                 min_vcpus: int = 2, docker_login: bool | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self._template = template
        self._disk_gib = int(disk_gib) if disk_gib is not None else None
        self._sandbox_timeout = int(sandbox_timeout_secs)
        self._headroom_mb = int(vm_memory_headroom_mb)
        self._min_vcpus = int(min_vcpus)
        self._docker_login = docker_login
        self._sandbox_id: str | None = None
        self._compose = _MunitoCompose(self)
        self.timings: dict[str, float] = {}

    @staticmethod
    @override
    def type() -> str:  # not one of Harbor's built-in EnvironmentType values
        return "munito"

    @property
    @override
    def _uses_compose(self) -> bool:
        return True

    @classmethod
    @override
    def resource_capabilities(cls) -> EnvironmentResourceCapabilities:
        return EnvironmentResourceCapabilities(cpu_request=True, cpu_limit=True,
                                               memory_request=True, memory_limit=True)

    @property
    @override
    def capabilities(self) -> EnvironmentCapabilities:
        return EnvironmentCapabilities(
            disable_internet=True,
            docker_compose=True,
            network_allowlist=True,
            network_allowlist_hostnames=True,
            network_allowlist_ipv4_addresses=True,
            network_allowlist_ipv4_cidrs=True,
            dynamic_network_policy=True,
        )

    @override
    def _validate_definition(self):
        has_definition = (self.environment_dir / "Dockerfile").exists() or (
            self.environment_dir / "docker-compose.yaml").exists()
        if not has_definition and not self.task_env_config.docker_image:
            raise FileNotFoundError(
                f"{self.environment_dir} has no Dockerfile or docker-compose.yaml, "
                "and the task names no docker_image")

    # ── munito.ai primitives ────────────────────────────────────────────

    def _vm_size(self) -> dict[str, int]:
        cpus = min(16, max(self._min_vcpus, int(self._effective_cpus or 2)))
        memory = int(self._effective_memory_mb or 4096) + self._headroom_mb
        memory = max(memory, 512 * cpus)
        memory = min(((memory + 255) // 256) * 256, 32_768)
        disk = self._disk_gib
        if disk is None:
            storage_gib = (self._effective_storage_mb or 10_240) / 1024
            disk = int(min(100, max(30, storage_gib * 3)))
        return {"vcpus": cpus, "memory_mib": memory, "disk_gib": disk}

    async def _create_sandbox(self) -> None:
        client = MunitoClient.get()
        body = {
            "template": self._template,
            **self._vm_size(),
            "timeout": self._sandbox_timeout,
            # The VM pulls the task image; the task's own policy is enforced with iptables.
            "internet": True,
            "metadata": {"harbor_session": self.session_id[:500],
                         "harbor_environment": self.environment_name[:500]},
        }
        t0 = time.monotonic()
        response = await client.request("POST", "/sandboxes", json=body, timeout=300,
                                        headers={"Idempotency-Key": f"harbor-{self.session_id}"[:255]})
        sandbox = response.json()
        self._sandbox_id = sandbox["id"]
        while sandbox.get("status") == "pending":
            await asyncio.sleep(1)
            sandbox = (await client.request("GET", f"/sandboxes/{self._sandbox_id}")).json()
        if sandbox.get("status") != "running":
            raise RuntimeError(f"munito.ai sandbox {self._sandbox_id} is {sandbox.get('status')}: {sandbox}")
        self.timings["create_s"] = round(time.monotonic() - t0, 2)
        self.logger.debug(f"munito.ai sandbox {self._sandbox_id} running ({body})")

    async def _vm_exec(self, command: str, *, env: dict[str, str] | None = None,
                       timeout_sec: int | None = None, cwd: str = "/") -> ExecResult:
        """Run a shell command as root on the VM (not in the task container)."""
        if not self._sandbox_id:
            raise RuntimeError("Sandbox not found. Please start the environment first.")
        body: dict[str, Any] = {"command": ["bash", "-c", command], "cwd": cwd}
        if env:
            body["env"] = env
        if timeout_sec is not None and 0 < timeout_sec <= SYNC_EXEC_MAX_SEC:
            body["timeout"] = max(1, int(timeout_sec))
            response = await MunitoClient.get().request(
                "POST", f"/sandboxes/{self._sandbox_id}/exec", json=body,
                timeout=timeout_sec + 60, retries=0)
            data = response.json()
            code = 124 if data.get("timed_out") else data["exit_code"]
            return ExecResult(stdout=data.get("stdout", ""), stderr=data.get("stderr", ""), return_code=code)
        return await self._background_exec(body, timeout_sec)

    async def _background_exec(self, body: dict[str, Any], timeout_sec: int | None) -> ExecResult:
        client = MunitoClient.get()
        body = {**body, "timeout": int(min(timeout_sec or self._sandbox_timeout, 86_400))}
        command = (await client.request("POST", f"/sandboxes/{self._sandbox_id}/commands",
                                        json=body, retries=0)).json()
        command_id = command["id"]
        stdout: list[str] = []
        stderr: list[str] = []
        out_n = err_n = 0
        try:
            while True:
                await asyncio.sleep(POLL_INTERVAL_SEC)
                state = (await client.request(
                    "GET", f"/sandboxes/{self._sandbox_id}/commands/{command_id}",
                    params={"stdout": out_n, "stderr": err_n})).json()
                stdout.append(state.get("stdout", ""))
                stderr.append(state.get("stderr", ""))
                out_n = state.get("stdout_bytes", out_n)
                err_n = state.get("stderr_bytes", err_n)
                if state["status"] != "running":
                    code = 124 if state.get("timed_out") else state.get("exit_code")
                    return ExecResult(stdout="".join(stdout), stderr="".join(stderr),
                                      return_code=1 if code is None else code)
        finally:
            try:
                await client.request("DELETE", f"/sandboxes/{self._sandbox_id}/commands/{command_id}",
                                     retries=1)
            except Exception:
                pass

    async def _put_file(self, data: bytes, path: str) -> None:
        if len(data) > FILE_MAX_BYTES:
            raise RuntimeError(f"{path}: {len(data)} bytes is above munito.ai's 100 MiB file limit")
        await MunitoClient.get().request(
            "PUT", f"/sandboxes/{self._sandbox_id}/files/content", params={"path": path},
            content=data, headers={"Content-Type": "application/octet-stream"}, timeout=600)

    async def _get_file(self, path: str) -> bytes:
        response = await MunitoClient.get().request(
            "GET", f"/sandboxes/{self._sandbox_id}/files/content", params={"path": path}, timeout=600)
        return response.content

    async def _wait_for_docker(self) -> None:
        last = ""
        for _ in range(90):
            result = await self._vm_exec("docker info --format '{{.ServerVersion}}'", timeout_sec=20)
            if result.return_code == 0:
                return
            last = result.stderr or result.stdout
            await asyncio.sleep(1)
        raise RuntimeError(f"Docker is not ready in the munito.ai sandbox: {last}")

    async def _maybe_docker_login(self) -> None:
        user, token = os.environ.get("DOCKERHUB_USERNAME"), os.environ.get("DOCKERHUB_TOKEN")
        if self._docker_login is False or not user or not token:
            return
        result = await self._vm_exec(f"docker login -u {shlex.quote(user)} --password-stdin <<'EOF'\n{token}\nEOF",
                                     timeout_sec=60)
        if result.return_code:
            self.logger.warning("docker login to Docker Hub failed; pulls stay anonymous")

    # ── network policy (iptables in the VM) ─────────────────────────────

    @property
    def _chain(self) -> str:
        # iptables chain names are at most 28 characters.
        return "HB-" + self._compose.project_name.replace("-", "").replace("_", "")[:24]

    @staticmethod
    def _allowlist_targets(policy: NetworkPolicy) -> tuple[list[str], list[str]]:
        """(IPv4 networks, hostnames). Hostnames resolve in the VM, where the containers connect from."""
        networks: set[str] = set()
        hostnames: set[str] = set()
        for entry in policy.allowed_hosts:
            kind = classify_network_allowlist_entry(entry)
            if kind in (NetworkAllowlistEntryType.IPV4_ADDRESS, NetworkAllowlistEntryType.IPV4_CIDR):
                networks.add(str(ipaddress.ip_network(entry, strict=False)))
            elif kind == NetworkAllowlistEntryType.HOSTNAME:
                hostnames.add(entry)
            else:
                raise ValueError(f"munito environment cannot allowlist {entry!r} ({kind})")
        return sorted(networks), sorted(hostnames)

    def policy_script(self, policy: NetworkPolicy) -> str:
        networks, hostnames = ([], [])
        if policy.network_mode == NetworkMode.ALLOWLIST:
            networks, hostnames = self._allowlist_targets(policy)
        project = shlex.quote(self._compose.project_name)
        lines = [
            "set -e",
            f"chain={shlex.quote(self._chain)}",
            f"bridges=$(for n in $(docker network ls -q --filter label=com.docker.compose.project={project}); do "
            "echo br-$(docker network inspect -f '{{.Id}}' $n | cut -c1-12); done)",
            "iptables -N $chain 2>/dev/null || iptables -F $chain",
            "iptables -C DOCKER-USER -j $chain 2>/dev/null || iptables -I DOCKER-USER 1 -j $chain",
        ]
        if policy.network_mode != NetworkMode.PUBLIC:
            lines.append("for br in $bridges; do")
            lines.append("  iptables -A $chain -i $br -o $br -j RETURN")
            lines.extend(f"  iptables -A $chain -i $br -d {shlex.quote(t)} -j RETURN" for t in networks)
            for host in hostnames:
                lines.append(f"  ips=$(getent ahostsv4 {shlex.quote(host)} | awk '{{print $1}}' | sort -u)")
                lines.append(f"  [ -n \"$ips\" ] || {{ echo 'allowlist host {host} does not resolve' >&2; exit 3; }}")
                lines.append("  for ip in $ips; do iptables -A $chain -i $br -d $ip -j RETURN; done")
            lines.append("  iptables -A $chain -i $br -j DROP")
            lines.append("done")
            # Containers must not reach the VM itself (its agent and Docker's own ports) either.
            lines.append("for br in $bridges; do iptables -C INPUT -i $br -j DROP 2>/dev/null "
                         "|| iptables -I INPUT 1 -i $br -j DROP; done")
        else:
            lines.append("for br in $bridges; do iptables -D INPUT -i $br -j DROP 2>/dev/null || true; done")
        lines.append("iptables -A $chain -j RETURN")
        return "\n".join(lines) + "\n"

    async def _write_policy(self, policy: NetworkPolicy) -> None:
        result = await self._vm_exec(self.policy_script(policy), timeout_sec=60)
        if result.return_code:
            raise RuntimeError(
                f"could not apply network policy {policy.network_mode}: {result.stderr or result.stdout}")

    @override
    async def _apply_network_policy(self, network_policy: NetworkPolicy) -> None:
        await self._write_policy(network_policy)

    # ── lifecycle ───────────────────────────────────────────────────────

    @override
    async def start(self, force_build: bool) -> None:
        t0 = time.monotonic()
        await self._create_sandbox()
        t1 = time.monotonic()
        await self._wait_for_docker()
        self.timings["docker_ready_s"] = round(time.monotonic() - t1, 2)
        await self._maybe_docker_login()
        await self._compose.start(force_build)
        # Before the agent or verifier runs anything, so the task's policy holds from the start.
        await self._write_policy(self.network_policy)
        await self.ensure_dirs(self._mount_targets(writable_only=True))
        await self._upload_environment_dir_after_start()
        self.timings["start_total_s"] = round(time.monotonic() - t0, 2)
        self.logger.info(f"munito.ai sandbox {self._sandbox_id} ready: {self.timings}")
        try:
            name = f"munito_timings_{self.environment_name.replace('/', '_')}_{uuid4().hex[:6]}.json"
            (self.trial_paths.trial_dir / name).write_text(json.dumps(
                {"sandbox_id": self._sandbox_id, "size": self._vm_size(), **self.timings}, indent=2))
        except Exception:
            pass

    @override
    async def stop(self, delete: bool):
        if not self._sandbox_id:
            return
        try:
            await MunitoClient.get().request("DELETE", f"/sandboxes/{self._sandbox_id}", retries=3)
        except Exception as error:
            self.logger.error(f"could not delete munito.ai sandbox {self._sandbox_id}: {error}")
        finally:
            self._sandbox_id = None

    # ── Harbor's environment surface, delegated to compose ──────────────

    @override
    async def exec(self, command: str, cwd: str | None = None, env: dict[str, str] | None = None,
                   timeout_sec: int | None = None, user: str | int | None = None) -> ExecResult:
        return await self._compose.exec(command, cwd=cwd or self.task_env_config.workdir,
                                        env=self._merge_env(env), timeout_sec=timeout_sec,
                                        user=self._resolve_user(user))

    @override
    async def upload_file(self, source_path: Path | str, target_path: str):
        await self._compose.upload_file(source_path, target_path)

    @override
    async def upload_dir(self, source_dir: Path | str, target_dir: str):
        await self._compose.upload_dir(source_dir, target_dir)

    @override
    async def download_file(self, source_path: str, target_path: Path | str):
        await self._compose.download_file(source_path, target_path)

    @override
    async def download_dir(self, source_dir: str, target_dir: Path | str):
        await self._compose.download_dir(source_dir, target_dir)

    @override
    async def is_dir(self, path: str, user: str | int | None = None) -> bool:
        return await self._compose.is_dir(path, user=self._resolve_user(user))

    @override
    async def is_file(self, path: str, user: str | int | None = None) -> bool:
        return await self._compose.is_file(path, user=self._resolve_user(user))

    @override
    def _compose_service_transport(self, service: str | None) -> ComposeServiceTransport:
        return self._compose
