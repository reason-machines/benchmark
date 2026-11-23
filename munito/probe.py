# /// script
# requires-python = ">=3.12"
# dependencies = ["httpx>=0.28", "e2b>=2"]
# ///
"""Raw sandbox latency probe: munito.ai vs E2B.

For each of N sandboxes (started CONCURRENCY at a time) it times: create (API
call until running), the first command, 10 sequential `true` round trips, a
1 MiB file write and read back, and delete. Prints one JSON line per sandbox
and a summary (p50/p90/max) per provider.

  uv run munito/probe.py munito --n 10 --concurrency 2 --template ubuntu --size default
  uv run munito/probe.py e2b --n 10 --concurrency 10

Needs MUNITO_API_KEY or E2B_API_KEY. Every sandbox it starts is deleted at the end.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import time

import httpx

MUNITO = os.environ.get("MUNITO_API_BASE", "https://api.munito.ai/sandboxes/v1")


async def munito_one(client: httpx.AsyncClient, args, index: int) -> dict:
    out: dict = {"provider": "munito", "i": index}
    body = {"template": args.template, "timeout": 600, "internet": args.internet}
    if args.size:
        body["size"] = args.size
    t = time.perf_counter()
    r = await client.post(f"{MUNITO}/sandboxes", json=body)
    if r.status_code >= 400:
        out["error"] = f"{r.status_code} {r.text[:300]}"
        return out
    sandbox = r.json()
    sid = sandbox["id"]
    while sandbox["status"] == "pending":
        await asyncio.sleep(0.25)
        sandbox = (await client.get(f"{MUNITO}/sandboxes/{sid}")).json()
    out["create_s"] = time.perf_counter() - t
    out["status"] = sandbox["status"]
    try:
        t = time.perf_counter()
        r = (await client.post(f"{MUNITO}/sandboxes/{sid}/exec", json={"command": ["true"]})).json()
        out["first_exec_s"] = time.perf_counter() - t
        rtts = []
        for _ in range(10):
            t = time.perf_counter()
            await client.post(f"{MUNITO}/sandboxes/{sid}/exec", json={"command": ["true"]})
            rtts.append(time.perf_counter() - t)
        out["exec_rtt_p50_s"] = statistics.median(rtts)
        blob = os.urandom(1 << 20)
        t = time.perf_counter()
        await client.put(f"{MUNITO}/sandboxes/{sid}/files/content", params={"path": "/tmp/blob"},
                         content=blob, headers={"Content-Type": "application/octet-stream"})
        back = (await client.get(f"{MUNITO}/sandboxes/{sid}/files/content", params={"path": "/tmp/blob"})).content
        out["file_1mib_roundtrip_s"] = time.perf_counter() - t
        out["file_ok"] = back == blob
        if args.template == "ubuntu":
            t = time.perf_counter()
            r = (await client.post(f"{MUNITO}/sandboxes/{sid}/exec",
                                   json={"command": "until docker info >/dev/null 2>&1; do sleep 0.2; done; nproc; free -m | awk '/Mem/{print $2}'; df -h / | tail -1",
                                         "timeout": 120})).json()
            out["docker_ready_s"] = time.perf_counter() - t
            out["vm"] = r.get("stdout", "").split()
    finally:
        t = time.perf_counter()
        await client.delete(f"{MUNITO}/sandboxes/{sid}")
        out["delete_s"] = time.perf_counter() - t
    return out


async def e2b_one(args, index: int) -> dict:
    from e2b import AsyncSandbox

    out: dict = {"provider": "e2b", "i": index}
    t = time.perf_counter()
    try:
        sandbox = await AsyncSandbox.create(template=args.e2b_template, timeout=600)
    except Exception as error:
        out["error"] = repr(error)[:300]
        return out
    out["create_s"] = time.perf_counter() - t
    try:
        t = time.perf_counter()
        await sandbox.commands.run("true")
        out["first_exec_s"] = time.perf_counter() - t
        rtts = []
        for _ in range(10):
            t = time.perf_counter()
            await sandbox.commands.run("true")
            rtts.append(time.perf_counter() - t)
        out["exec_rtt_p50_s"] = statistics.median(rtts)
        blob = os.urandom(1 << 20)
        t = time.perf_counter()
        await sandbox.files.write("/tmp/blob", blob)
        back = await sandbox.files.read("/tmp/blob", format="bytes")
        out["file_1mib_roundtrip_s"] = time.perf_counter() - t
        out["file_ok"] = bytes(back) == blob
    finally:
        t = time.perf_counter()
        await sandbox.kill()
        out["delete_s"] = time.perf_counter() - t
    return out


def summary(rows: list[dict]) -> dict:
    keys = ["create_s", "first_exec_s", "exec_rtt_p50_s", "file_1mib_roundtrip_s", "docker_ready_s", "delete_s"]
    result: dict = {"n": len(rows), "errors": sum(1 for r in rows if "error" in r)}
    for key in keys:
        values = sorted(r[key] for r in rows if key in r)
        if values:
            result[key] = {"p50": round(statistics.median(values), 3),
                           "p90": round(values[min(len(values) - 1, int(0.9 * len(values)))], 3),
                           "max": round(values[-1], 3)}
    return result


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("provider", choices=["munito", "e2b"])
    parser.add_argument("--n", type=int, default=10)
    parser.add_argument("--concurrency", type=int, default=2)
    parser.add_argument("--template", default="base", help="munito template")
    parser.add_argument("--size", default=None, help="munito size preset")
    parser.add_argument("--internet", action="store_true")
    parser.add_argument("--e2b-template", default="base")
    args = parser.parse_args()
    semaphore = asyncio.Semaphore(args.concurrency)
    client = httpx.AsyncClient(headers={"Authorization": f"Bearer {os.environ.get('MUNITO_API_KEY', '')}"},
                               timeout=httpx.Timeout(300.0))

    async def one(i: int) -> dict:
        async with semaphore:
            row = await (munito_one(client, args, i) if args.provider == "munito" else e2b_one(args, i))
            print(json.dumps({k: (round(v, 3) if isinstance(v, float) else v) for k, v in row.items()}), flush=True)
            return row

    rows = await asyncio.gather(*(one(i) for i in range(args.n)))
    print(json.dumps({"summary": args.provider, **summary(list(rows))}))


if __name__ == "__main__":
    asyncio.run(main())
