# Egress verification (T099)

**Date:** 2026-08-20 · **Scope:** orchestrator control plane, bounded agent runtime, sandboxed
`run_tests`, integration sandbox, URL shortener · **Method:** live processes and live containers

This is a verification record, not a design document. Every result below came from a running
process or a running container. Where a check could have passed for the wrong reason, the
control that rules that out is named alongside it.

The exercise found **four real defects**, all now fixed and covered by regression tests. The
most serious was that the orchestrator's egress allow-list, though fully implemented and
documented, **was never installed in the running application** — the guard was inert, and no
unit test could have noticed, because the policy object it tested behaved correctly in
isolation. That is precisely the gap this task existed to close.

---

## 1. Topology tested

```
                    ┌──────────────────────────────────────────┐
                    │ orchestrator process                     │
   allowed ◄────────┤  socket guard installed at import time   ├────────► DENIED
   api.anthropic.com│  (src/api/app.py → install_socket_guard) │  everything else
   configured PG    └───────────────────┬──────────────────────┘
   loopback                             │ docker CLI (orchestrator only)
                                        ▼
      ┌─────────────────────────────────────────────────────────────┐
      │ unit / workflow / failure layers        --network none      │
      │   disposable surface copy, non-root, cap-drop ALL           │
      ├─────────────────────────────────────────────────────────────┤
      │ integration layer            --network <internal>           │
      │   test runner  ◄──────────►  disposable PostgreSQL          │
      │   no Docker socket · no route off host · no external DNS    │
      └─────────────────────────────────────────────────────────────┘
```

The agent's four tools are the only model-visible capability. No tool reaches the network; the
Claude endpoint belongs to the orchestrator, never to agent-authored code.

## 2. Allowed destinations

| Destination | Who may reach it | Verified by |
|---|---|---|
| `api.anthropic.com` (or configured `ANTHROPIC_BASE_URL`) | orchestrator process only | live `getaddrinfo` through the installed guard — permitted and resolved |
| Configured PostgreSQL host (from `ORCHESTRATOR_DB_URL`) | orchestrator process only | live `SELECT 1` over a real connection to `192.168.68.51:55433`, a **non-loopback** address, through the installed guard |
| `localhost` / `127.0.0.1` / `::1` | orchestrator process | health checks and local database |
| Disposable PostgreSQL container | integration test runner, on an `--internal` network | live `psql -tAc 'select 1'` from inside the runner container |

## 3. Denied destinations

| Destination | Result |
|---|---|
| `example.com`, `github.com`, `registry.npmjs.org`, `pypi.org` | `EgressDenied` (`forbidden`) at DNS resolution |
| `140.82.121.4:443` (raw address) | `EgressDenied` at connect |
| A listening socket on this host's own LAN address | `EgressDenied`, **and the listener accepted nothing** |
| `1.1.1.1:443`, `93.184.216.34:80` from the integration test runner | unreachable |
| DNS for `example.com` **and `api.anthropic.com`** from the test runner | unavailable |
| `host.docker.internal:5432` from the test runner | unreachable |
| `/var/run/docker.sock` in any sandbox container | not present |

Observed denial text — the host is named, credentials are not:

```
egress to 'registry.npmjs.org' is not permitted; allow-list is ['192.168.68.51', 'api.anthropic.com']
egress to '140.82.121.4' is not permitted
```

## 4. Method

```bash
# Orchestrator control plane, agent boundary, fail-closed, audit safety
orchestrator$ ../.venv/bin/python -m pytest tests/failure -q          # 157 passed

# Real integration topology (creates a real internal network + PostgreSQL)
orchestrator$ ../.venv/bin/python -m pytest tests/failure/test_integration_sandbox_topology.py -q

# Shortener: zero outbound requests to caller-supplied destinations
shortener$ JAVA_HOME=$(/usr/libexec/java_home -v 21) mvn -B -Dtest=EgressTest test   # 5 passed

# Live proof against a real database on a non-loopback address
$ docker run -d --rm --name t099-pg -p 192.168.68.51:55433:5432 \
    -e POSTGRES_PASSWORD=… -e POSTGRES_DB=orchestrator_db postgres:16-alpine
$ ORCHESTRATOR_DB_URL="postgresql+psycopg://postgres:…@192.168.68.51:55433/orchestrator_db" \
    .venv/bin/python live_egress_proof.py
```

New verification suites:

| File | Covers |
|---|---|
| `orchestrator/tests/failure/test_egress_boundary.py` | control-plane allow/deny, in a real subprocess |
| `orchestrator/tests/failure/test_integration_sandbox_topology.py` | integration network topology, real containers |
| `orchestrator/tests/failure/test_fail_closed_real.py` | fail-closed against a really-unreachable daemon |
| `orchestrator/tests/failure/test_audit_secret_safety.py` | credentials never reach an audit record |
| `shortener/src/test/java/com/schwab/shortener/failure/EgressTest.java` | FR-018 — destinations are never fetched |

## 5. Observed results

### 5.1 Orchestrator control-plane egress

The running application — `from src.api.app import app` in a fresh interpreter — denies
`example.com` at DNS and denies `urllib.request.urlopen` against it, while resolving
`api.anthropic.com` and connecting to the configured database. The typed failure is
`EgressDenied`, whose code is `forbidden`.

The denied-destination proof does not rest on an exception alone. A listener is bound on this
host's real LAN address, the guard refuses the connection, `listener.accept()` times out — and
then, with the guard removed, the same connection succeeds and is accepted. The refusal was the
policy, not an unreachable address.

### 5.2 Agent tool boundary

The request this runtime would send declares exactly:

```
tools: ['read_file', 'write_file', 'run_tests', 'report']
keys:  ['betas', 'max_tokens', 'messages', 'model', 'output_config', 'system', 'thinking', 'tools']
```

`mcp_servers` absent · `container` absent · no `web_search`, `web_fetch`, `code_execution`,
`bash`, or text-editor tool · no HTTP, shell, git, or package-install tool. The strings
themselves do not appear anywhere in the serialised request. `run_tests` accepts an enum layer;
commands come from a frozen argv table, so no command, path, host, or port is model-supplied.

### 5.3 Sandboxed unit / workflow / failure layers

Verified inside real `--network none` containers: an arbitrary internet host is unreachable,
external DNS is unavailable, `/var/run/docker.sock` is absent, host home and host secrets do not
resolve at all, sibling surfaces are absent, the environment carries no secrets, the container
runs non-root with `NoNewPrivs:1`, and mutations reach only the disposable copy.

### 5.4 Integration sandbox

The runtime's own topology was constructed and probed from inside the runner container:
PostgreSQL answers a real `select 1` over the PostgreSQL protocol; `1.1.1.1:443` and
`93.184.216.34:80` are unreachable; DNS for `example.com` and for `api.anthropic.com` is
unavailable; `host.docker.internal:5432` is unreachable; the Docker socket is not mounted; only
the disposable copy is visible. `docker network inspect` confirms `Internal: true`.

**Control against a vacuous pass.** A missing binary and a blocked network both yield a non-zero
exit code, so the identical probe script is also run on an ordinary bridge network, where
`nc -z 1.1.1.1 443` and `getent hosts example.com` both return 0. The tools work; the network is
what stops them.

### 5.5 Fail-closed

With `DOCKER_HOST` pointed at a socket that does not exist — a genuinely unreachable daemon, not
a monkeypatch — `run_tests` raises `SandboxUnavailable`, and a `subprocess.run` interceptor
confirms **no non-`docker` process was executed**: there is no host fallback. With the daemon up
and a never-built image named, `SandboxUnavailable` again, and `docker image inspect` afterwards
confirms the runtime did not build or pull it. In a separate interpreter the same conditions
print `SANDBOX_UNAVAILABLE` and never `RAN`.

The run's response: `safe_stopped=True`, `completed=False`, reason `sandbox unavailable: …`,
audit event `SAFE_STOP_SANDBOX_UNAVAILABLE`, `changes == []`, and `violations == 0` — a missing
boundary is not a retryable tool violation.

### 5.6 Audit safety

Records emitted on these paths carry `run_id` and `trace_id`, name the reason, and contain no
credentials. Sentinel API keys and database passwords planted in the environment appear in no
error message and no audit payload. The denied host *is* named — that is intended and necessary
for the record to be useful.

## 6. Defects found and fixed

| # | Defect | Evidence | Fix |
|---|---|---|---|
| 1 | **The egress guard was never installed.** `install_socket_guard` had no call site; the running orchestrator had unrestricted egress. | A real process importing `src.api.app` resolved `example.com` successfully. | Installed at import time in `src/api/app.py`, before any router or connection pool exists. |
| 2 | **The allow-list read a variable the application does not use.** It took the database host from `ORCHESTRATOR_DB_HOST` while `api.deps.get_engine` connects via `ORCHESTRATOR_DB_URL`. Once the guard was installed, a non-loopback database would have been denied — the kind of breakage that gets a control switched off rather than fixed. | `build_policy()` with a DSN naming `db.internal` produced an allow-list of `['api.anthropic.com']` only. | `build_policy` derives the host from `ORCHESTRATOR_DB_URL` when `ORCHESTRATOR_DB_HOST` is unset. |
| 3 | **Credentials echoed on the failure path.** `_host_of` interpolated the raw URL into `EgressDenied`, so an unparseable DSN or a base URL with embedded basic-auth printed its password. | `EgressDenied("cannot determine host from 'not-a-url://user:SUPERSECRET@'")`. | `_redacted()` strips userinfo before any URL is formatted into a message. |
| 4 | **Audit secret detection was key-only.** Audit details are free text (`{"detail": str(exc)}`), so a connection string in a value passed the check unexamined. | `_reject_secrets({"detail": "…postgres:PASSWORD@host…"})` returned cleanly. | Value-side detection for URL userinfo, API-key shapes, auth headers, and inline credential assignments. The error names the pattern, never the matched text. |

Each fix is pinned by a regression test that was **confirmed to fail when the fix is reverted**:
reverting 1 fails 2 tests, reverting 2 fails 3, reverting 4 fails 2.

No change was made to the approved egress architecture. Defects 1 and 2 make the approved design
take effect; 3 and 4 harden existing controls on their failure paths. No firewall or network
product was added.

## 7. Limitations

* **A raw `socket.socket().connect()` bypasses the guard, by design.** The guard wraps
  `getaddrinfo` and `create_connection` — the entry points every stdlib and third-party HTTP
  client uses — and cannot wrap the syscall those wrappers themselves call. This is why the
  guard is *defense in depth for the orchestrator's own code*, and why the boundary for
  agent-authored code is a container with `--network none` instead. The limitation is asserted
  by a test (`test_a_raw_socket_connect_bypasses_the_guard_by_design`) so it stays a recorded
  property rather than a surprise.
* **The guard is process-local.** It protects the orchestrator process; it says nothing about a
  child process. Containment of children is the container's job.
* **No host-level firewall was verified**, because none is part of the approved design. These
  results describe application- and container-level containment only.
* **Single-host verification.** Client, server, and containers share one machine. A deployed
  topology would add real network segmentation, which these tests neither exercise nor need.
* **The model endpoint was resolved, not called.** Proving that `api.anthropic.com` is permitted
  required DNS, not an authenticated request; no API key was transmitted during verification.
* **`ANTHROPIC_BASE_URL` is trusted configuration.** Pointing it at an attacker-controlled host
  would add that host to the allow-list. It is operator-supplied, like the database DSN.
* **The shortener's proof is scoped to its own request paths.** `EgressTest` proves the service
  does not fetch a caller-supplied destination during creation, resolution, analytics,
  revocation, or rejection. It is not a whole-JVM egress guard; the shortener has no allow-list
  mechanism because it makes no outbound calls at all.
