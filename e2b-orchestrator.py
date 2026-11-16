#!/usr/bin/env -S uv run -q
# /// script
# requires-python = ">=3.10"
# dependencies = ["e2b==2.64.0"]
# ///
"""Runs run.sh inside an e2b sandbox that stays alive for the whole run.

Harbor's orchestrator holds every trial: if it dies (a laptop sleeps, a cloud
session parks), every running trial dies with it. Here it runs in its own e2b
sandbox, so nothing local has to stay up:

  uv run e2b-orchestrator.py start [--max-hours 24] -- deepswe -i <task>
  uv run e2b-orchestrator.py status <sandbox-id>
  uv run e2b-orchestrator.py fetch <sandbox-id> [--kill]

`start` uploads this checkout's tracked files, installs the pinned Harbor and
starts run.sh with the run.sh variables set here (keys included; they go to a
mode-600 file in the sandbox, never to a command line). Keep-alive: the sandbox
is created with a one-hour timeout, and a loop inside it pushes the timeout one
hour ahead every five minutes for as long as run.sh is alive, up to --max-hours.
When run.sh exits (or dies), the loop sets a final GRACE_SEC window to fetch the
results in, so an idle sandbox is never kept. `fetch` copies jobs/ and logs/
back into this checkout, where score.py reads them.
"""
from __future__ import annotations

import argparse
import io
import os
import shlex
import subprocess
import sys
import tarfile
from pathlib import Path

from e2b import Sandbox, Template

ROOT = Path(__file__).resolve().parent
TEMPLATE = "reason-bench-orchestrator-4x8"
HOME = "/home/user"
BENCH = f"{HOME}/bench"
WINDOW_SEC = 3600      # how far ahead each heartbeat pushes the timeout
HEARTBEAT_SEC = 300    # how often it does
GRACE_SEC = 7200       # how long the sandbox stays after run.sh exits
HARBOR = 'harbor[e2b,modal]==0.22.0'
ADAPTER = 'reason-machines-harbor==0.3.51'
# run.sh's inputs (README.md lists them). Only these reach the sandbox.
PASS_ENV = ("REASON_API_KEY", "E2B_API_KEY", "ANTHROPIC_API_KEY", "MODAL_TOKEN_ID", "MODAL_TOKEN_SECRET",
            "MODAL_PROFILE", "MODEL", "EFFORT", "HARBOR_ENV", "PART", "ATTEMPTS", "HARNESS", "RUN",
            "E2B_CONCURRENCY", "MODAL_CONCURRENCY", "SCREEN_JUDGE", "REASON_EPHEMERAL_RCUS")

KEEPALIVE = r"""#!/usr/bin/env bash
# Pushes this sandbox's timeout ahead while run.sh is alive; written by e2b-orchestrator.py.
set -u
cd "$(dirname "$0")"
. ./.run.env
deadline=$(( $(date +%s) + MAX_SEC ))
extend() {
  if curl -fsS -m 30 -o /dev/null -X POST -H "X-API-Key: $E2B_API_KEY" -H 'content-type: application/json' \
       -d "{\"timeout\": $1}" "https://api.e2b.dev/sandboxes/$ORCH_SANDBOX_ID/timeout"; then
    echo "$(date -u +%FT%TZ) timeout set to $1s ($2)"
  else
    echo "$(date -u +%FT%TZ) could not set timeout to $1s ($2)"
  fi
}
alive() { [ -f logs/run.pid ] && kill -0 "$(cat logs/run.pid)" 2>/dev/null; }
sleep 5
while alive && [ ! -f logs/exit-code ]; do
  if [ "$(date +%s)" -ge "$deadline" ]; then echo "$(date -u +%FT%TZ) reached MAX_SEC; no more extensions"; exit 0; fi
  extend "$WINDOW_SEC" "run.sh alive"
  sleep "$HEARTBEAT_SEC"
done
extend "$GRACE_SEC" "run.sh exited with $(cat logs/exit-code 2>/dev/null || echo 'no exit code: it died')"
"""


def ensure_template() -> None:
    if Template.alias_exists(TEMPLATE):
        return
    print(f"Building e2b template {TEMPLATE} (once)...", file=sys.stderr)
    template = (Template().from_python_image("3.12")
                .apt_install(["git", "curl", "procps"])
                .pip_install(["uv"]))
    # e2b's default 512 MB can't hold Harbor; 4 CPUs / 8 GB hold about 80 concurrent trials.
    Template.build(template, alias=TEMPLATE, cpu_count=4, memory_mb=8192)


def checkout_tarball() -> bytes:
    files = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True).stdout
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as tar:
        for name in filter(None, files.decode().split("\0")):
            if (ROOT / name).exists():
                tar.add(ROOT / name, arcname=name)
    return buffer.getvalue()


def run(sandbox: Sandbox, command: str, timeout: int = 600) -> str:
    result = sandbox.commands.run(command, timeout=timeout)
    return result.stdout


def start(args: argparse.Namespace) -> None:
    if not os.environ.get("E2B_API_KEY"):
        sys.exit("Set E2B_API_KEY")
    if not args.run_args:
        sys.exit("Pass run.sh's arguments after --, for example: -- deepswe -i datacurve/<task>")
    ensure_template()
    sandbox = Sandbox.create(template=TEMPLATE, timeout=WINDOW_SEC,
                             metadata={"purpose": "reason-bench-orchestrator", "run": os.environ.get("RUN", "")})
    print(f"Orchestrator sandbox {sandbox.sandbox_id}", flush=True)
    sandbox.files.write(f"{HOME}/bench.tgz", checkout_tarball())
    run(sandbox, f"mkdir -p {BENCH}/logs && tar xzf {HOME}/bench.tgz -C {BENCH} && rm {HOME}/bench.tgz")
    run(sandbox, f"uv tool install -q {shlex.quote(HARBOR)} --with {shlex.quote(ADAPTER)}", timeout=900)

    env = {name: os.environ[name] for name in PASS_ENV if os.environ.get(name)}
    env |= {"ORCH_SANDBOX_ID": sandbox.sandbox_id, "MAX_SEC": str(int(args.max_hours * 3600)),
            "WINDOW_SEC": str(WINDOW_SEC), "HEARTBEAT_SEC": str(HEARTBEAT_SEC), "GRACE_SEC": str(GRACE_SEC),
            "PATH": f"{HOME}/.local/bin:/usr/local/bin:/usr/bin:/bin"}
    sandbox.files.write(f"{BENCH}/.run.env", "".join(f"export {k}={shlex.quote(v)}\n" for k, v in env.items()))
    sandbox.files.write(f"{BENCH}/keepalive.sh", KEEPALIVE)
    run(sandbox, f"chmod 600 {BENCH}/.run.env && chmod +x {BENCH}/keepalive.sh")

    run_args = " ".join(shlex.quote(a) for a in args.run_args)
    launcher = (f"cd {BENCH} && . ./.run.env && echo $$ > logs/run.pid && "
                f"{{ ./run.sh {run_args}; echo $? > logs/exit-code; }} > logs/orchestrator.log 2>&1")
    run(sandbox, f"nohup bash -c {shlex.quote(launcher)} > /dev/null 2>&1 &")
    run(sandbox, f"cd {BENCH} && nohup ./keepalive.sh >> logs/keepalive.log 2>&1 &")
    print(run(sandbox, f"sleep 15; cd {BENCH}; cat logs/orchestrator.log; cat logs/keepalive.log", timeout=60))
    print(f"Started. Check it:  uv run e2b-orchestrator.py status {sandbox.sandbox_id}")


def status(args: argparse.Namespace) -> None:
    sandbox = Sandbox.connect(args.sandbox_id)
    info = sandbox.get_info()
    print(f"{args.sandbox_id}: started {info.started_at:%FT%TZ}, ends {info.end_at:%FT%TZ} unless extended")
    print(run(sandbox, f"cd {BENCH}; "
                       "if [ -f logs/exit-code ]; then echo \"run.sh exited with $(cat logs/exit-code)\"; "
                       "elif kill -0 \"$(cat logs/run.pid)\" 2>/dev/null; then echo 'run.sh running'; "
                       "else echo 'run.sh died without an exit code'; fi; "
                       "tail -n 3 logs/keepalive.log; echo; tail -n 15 logs/orchestrator.log; "
                       "for f in logs/*-e2b.log logs/*-modal.log; do [ -f \"$f\" ] && echo \"== $f\" && tail -n 15 \"$f\"; done; true",
              timeout=60))


def fetch(args: argparse.Namespace) -> None:
    sandbox = Sandbox.connect(args.sandbox_id)
    run(sandbox, f"cd {BENCH} && tar czf {HOME}/results.tgz jobs logs --exclude='*.pid' 2>/dev/null || true", timeout=600)
    data = sandbox.files.read(f"{HOME}/results.tgz", format="bytes")
    with tarfile.open(fileobj=io.BytesIO(bytes(data)), mode="r:gz") as tar:
        tar.extractall(ROOT, filter="data")
    print(f"Copied jobs/ and logs/ from {args.sandbox_id} into {ROOT}")
    if args.kill:
        sandbox.kill()
        print(f"Killed {args.sandbox_id}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("start", help="start run.sh in a new orchestrator sandbox")
    p.add_argument("--max-hours", type=float, default=24.0, help="stop extending the sandbox after this long")
    p.add_argument("run_args", nargs=argparse.REMAINDER, help="-- then run.sh's arguments")
    p = sub.add_parser("status", help="show whether run.sh is alive and its latest log lines")
    p.add_argument("sandbox_id")
    p = sub.add_parser("fetch", help="copy jobs/ and logs/ back into this checkout")
    p.add_argument("sandbox_id")
    p.add_argument("--kill", action="store_true", help="kill the sandbox afterwards")
    args = parser.parse_args()
    if args.command == "start" and args.run_args[:1] == ["--"]:
        args.run_args = args.run_args[1:]
    {"start": start, "status": status, "fetch": fetch}[args.command](args)


if __name__ == "__main__":
    main()
