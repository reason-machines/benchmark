# munito.ai as a Harbor environment (prototype)

Status: **prototype, draft.** The environment class and probe here are for
evaluating [munito.ai Sandboxes](https://docs.munito.ai/sandboxes) as an
alternative to e2b for this repository's runs. Nothing in the published
pipeline uses it unless you set `HARBOR_ENV=munito`.

## How munito.ai sandboxes work

| | munito.ai | e2b (what `run.sh` uses today) |
|---|---|---|
| Isolation | Linux microVM, own kernel, disk and network | Firecracker microVM |
| API | REST, `https://api.munito.ai/sandboxes/v1`, `Authorization: Bearer $MUNITO_API_KEY`; npm CLI/SDK `@munitoai/cli`; no Python SDK | Python/JS SDK (`e2b`) |
| Root filesystem | Fixed templates only: `base` (Debian 12), `ubuntu` (Ubuntu 24.04, systemd, Docker + Compose + Buildx running), `agent`, `desktop`. **No custom image or Dockerfile template.** | Template built from the task's image or Dockerfile (`Template.from_image`), cached per alias |
| Image ENV / WORKDIR | n/a: the task runs as a container, so Docker applies them | Dropped; the adapter re-applies ENV (`ReasonE2BEnvironment`) |
| Size | 1-16 vCPU, 512 MiB-32 GiB (>=512 MiB per vCPU), 10-100 GiB disk (`disk_gib`) | Capped at 8 vCPU / 8 GiB for our account (why SWE-Atlas runs at 8/8) |
| Lifetime | 10 s-24 h (`timeout`), 2 h during the trial; persistent sandboxes pause on timeout | Up to 24 h |
| Exec | `POST /exec` (sync, <=1,800 s, 1 MiB per stream, optional NDJSON stream); `POST /commands` background (<=24 h, poll with byte offsets, 16 per sandbox) | SDK commands, background + wait |
| Files | `PUT/GET /files/content?path=` (<=100 MiB per file), list, delete | SDK read/write, batch write |
| Network | `internet: true/false` only (off by default); no allowlist. Private networks between sandboxes; ports at `https://<port>-<id>.munito.run`; SSH | Allowlist (`allow_out`/`deny_out`) at create and at runtime |
| Persistence | `persistent: true` -> pause/resume with memory; `fork` up to 16 copies at once | Pause/resume |
| GPUs | Internal orgs only | No |
| Concurrency | Plan: 2 (trial), 50 Starter $15/mo, 200 Pro $95/mo, 1,000 Scale $495/mo, 2,000 Fleet $1,995/mo; plan fee comes back as credits. Org-wide cap on open commands/file transfers (`too_many_streams`, number undocumented) | Plan quota (run-pass.sh uses 80) |
| Price | Per second for full size, idle or busy: $0.0072/vCPU-h + $0.0009/GiB-h up to 8 vCPU/16 GiB (4 vCPU/8 GiB = $0.036/h; 8/16 = $0.072/h) | Higher; munito's own table puts a 2 vCPU/4 GiB idle weekend at 9.2x munito's price on e2b |
| Region | EU or US host per org (`munito-region` header) | US |
| Errors | RFC 9457 problems with a stable `code` (`sandbox_limit_reached`, `no_capacity` + `Retry-After`, `start_unknown`, `too_many_streams`, `trial_limit`, `credits_low`, ...); create takes an `Idempotency-Key` | SDK exceptions |

Sources: [Sandboxes](https://docs.munito.ai/sandboxes),
[Templates](https://docs.munito.ai/sandboxes/templates),
[Commands](https://docs.munito.ai/sandboxes/commands),
[Pricing and limits](https://docs.munito.ai/sandboxes/pricing),
[Pause and fork](https://docs.munito.ai/sandboxes/persistence),
[API reference](https://docs.munito.ai/llms.txt). Sandboxes are a public
preview; the API, limits and prices can change.

## How the benchmark uses e2b today

`run.sh` runs `--env reasonmachines_harbor.environment:ReasonE2BEnvironment`
(from [reason-machines-harbor](https://github.com/reason-machines/reason-machines-harbor),
0.3.51 on PyPI). That class subclasses Harbor 0.22's `E2BEnvironment`, which
builds an e2b template from each task's image, and adds the image's ENV (and a
`/etc/profile.d` PATH script) that e2b drops. The agent (`ReasonAgent`) only
needs `exec`, file upload/download and outbound access to
`api.reasonmachines.com` and `relay.reasonmachines.com`.

e2b cannot host 21 of 66 Terminal-Bench tasks (11 multi-container, 4 above
8 vCPU/8 GiB, 3 GPU, 3 failing reference solutions), 2 DeepSWE tasks (image ENV
missing in the grader) and 25 SWE-Atlas tasks (dead Debian 11 apt sources
break e2b provisioning). Those run on Modal.

## The prototype: `munito_environment.MunitoEnvironment`

Because munito.ai has no custom-image templates, the environment runs every
task the way Harbor already runs compose tasks on Daytona, Modal and GKE: one
`ubuntu` microVM per environment, the task image pulled (or its Dockerfile
built) inside it, and `docker compose` starting `main` and any sidecars. It
reuses Harbor's `DinDComposeOps` for exec, two-hop file transfer and
per-service operations, and implements its four primitives with the REST API
(sync exec up to 1,700 s, background command + polling beyond that, file
PUT/GET, tar for directories).

- **Network policy** is enforced inside the VM with an iptables chain per
  compose project under `DOCKER-USER` (and an `INPUT` drop so containers cannot
  reach the VM): public, no-network, and IPv4/CIDR/hostname allowlists (names
  resolved in the VM), switchable at runtime for Harbor's per-phase policies.
  The VM itself has internet so it can pull the image.
- **Sizing:** VM vCPUs = task CPUs (min 2), memory = task memory + 1 GiB for
  dockerd, disk = max(30, 3x task storage) GiB, all overridable with `--ek`.
- **What it should unlock vs e2b** (to be verified): multi-container tasks,
  tasks above 8 vCPU/8 GiB (up to 16/32), native image ENV, images whose apt
  sources break e2b's template build. Not GPU tasks.
- **Cost of the approach:** every trial pulls its image into a fresh VM. e2b
  caches a built template per task. Pause/fork (one warm VM per image, forked
  per attempt) or a registry mirror would remove the repeated pull; not done
  here.

```bash
export MUNITO_API_KEY=...            # console.munito.ai/keys
HARBOR_ENV=munito ./run.sh terminal-bench -i terminal-bench/interleaved-vigenere
# or directly:
PYTHONPATH=munito harbor run ... --env munito_environment:MunitoEnvironment
```

## Measurements

Raw API probe (`uv run munito/probe.py e2b|munito ...`), from a Reason cloud
machine, 10 sandboxes:

| | e2b `base` | munito.ai |
|---|---|---|
| Create (p50 / p90) | 0.42 s / 0.47 s | pending |
| First exec | 0.12 s | pending |
| Exec round trip (p50) | 0.13 s | pending |
| 1 MiB write + read | 1.30 s | pending |
| Errors | 0 / 10 | pending |

Harbor oracle runs (reference solution + verifier), Terminal-Bench 4.0:

| Task | e2b env setup | e2b result | munito.ai env setup | munito.ai result |
|---|---|---|---|---|
| interleaved-vigenere | 1.8 s (cached template) | 1.0 | pending | pending |
| html-js-filter | 2.2 s | 1.0 | pending | pending |
| sound-change-cascade | 2.1 s | 1.0 | pending | pending |
