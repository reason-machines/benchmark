# /// script
# requires-python = ">=3.12"
# dependencies = ["modal>=1.6,<2"]
# ///
"""Make sure a benchmark job leaves no Modal sandboxes (and no GPUs) running.

Each Modal job runs in its own app. This stops only that app, by exact name, and only
names that start with "reason-bench-", so other apps in the workspace are never touched.

Usage (run with `uv run modal_guard.py ...`; MODAL_PROFILE selects the workspace):
  modal_guard.py fresh APP       fail if APP is already running
  modal_guard.py stop APP        stop APP, then wait until none of its sandboxes run
  modal_guard.py watch PID APP   wait for PID to exit, then stop APP
  modal_guard.py list            print every running reason-bench- app
"""
import json
import os
import subprocess
import sys
import time

import modal

PREFIX = "reason-bench-"


def modal_json(*args: str) -> list[dict]:
    output = subprocess.run([sys.executable, "-m", "modal", *args, "--json"],
                            check=True, capture_output=True, text=True)
    return json.loads(output.stdout)


def live_apps(name: str | None = None) -> list[dict]:
    return [app for app in modal_json("app", "list")
            if app["state"] not in ("stopped", "stopping")
            and (app["description"] == name if name else app["description"].startswith(PREFIX))]


def running(name: str, sandboxes: list[str]) -> list[str]:
    # `modal container list` can miss sandboxes, so poll each sandbox by ID as well.
    left = [s for s in sandboxes if modal.Sandbox.from_id(s).poll() is None]
    return left + [c["container_id"] for c in modal_json("container", "list") if c["app_name"] == name]


def stop(name: str) -> None:
    sandboxes = []
    for app in live_apps(name):
        sandboxes += [s.object_id for s in modal.Sandbox.list(app_id=app["app_id"])]
        for sandbox_id in sandboxes:
            modal.Sandbox.from_id(sandbox_id).terminate()
        subprocess.run([sys.executable, "-m", "modal", "app", "stop", "-y", app["app_id"]], check=False)
    deadline = time.time() + 180
    while (left := running(name, sandboxes)) and time.time() < deadline:
        time.sleep(10)
    if left:
        sys.exit(f"{name}: still running after stop: {' '.join(left)}")
    print(f"{name}: stopped; {len(sandboxes)} sandboxes terminated, 0 running")


def main() -> None:
    command, *args = sys.argv[1:] or ["help"]
    if command == "list":
        print("\n".join(app["description"] for app in live_apps()) or "no running reason-bench- apps")
        return
    if not args or not args[-1].startswith(PREFIX):
        sys.exit(__doc__)
    name = args[-1]
    if command == "fresh":
        if live_apps(name):
            sys.exit(f"{name} is already running; use a new job name")
    elif command == "stop":
        stop(name)
    elif command == "watch":
        pid = int(args[0])
        while True:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            time.sleep(15)
        stop(name)
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
