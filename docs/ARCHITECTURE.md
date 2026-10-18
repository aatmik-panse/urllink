# Architecture

## Components

```mermaid
flowchart LR
  user([Browser / curl]) -->|127.0.0.1:8082| np[kind node<br/>NodePort 30080]
  subgraph cluster[kind cluster]
    subgraph ns_expenses[namespace expenses &middot; PSS restricted]
      svc[Service expenses<br/>ClusterIP/NodePort :80] --> api1[API pod]
      svc --> api2[API pod]
      api1 & api2 -->|5432| pgsvc[headless Service<br/>expenses-postgres]
      pgsvc --> pg[(PostgreSQL<br/>StatefulSet + PVC)]
      hpa[HPA] -.scales.-> api1
      pdb[PDB minAvailable 1] -.protects.-> api2
    end
    subgraph ns_mon[namespace monitoring]
      prom[Prometheus] -->|scrape /metrics| api1
      prom --> am[Alertmanager]
      graf[Grafana] --> prom
    end
    subgraph ns_obs[namespace observability]
      jaeger[Jaeger v2]
    end
    api1 -->|OTLP/HTTP 4318| jaeger
  end
  np --> svc
```

| Component | Kind | Why this workload type |
|---|---|---|
| API (FastAPI + Uvicorn) | `Deployment`, 2+ replicas, HPA 2-5 | Stateless; any pod can serve any request, so replicas are interchangeable and can roll one at a time. |
| PostgreSQL 17 | `StatefulSet` (1 replica) + `volumeClaimTemplate` | Needs a stable identity and storage that follows the pod across restarts. One replica: no HA (see limitations). |
| Service `expenses` | ClusterIP (default), NodePort locally | Single stable entry point; load-balances across *ready* pods only. |
| Service `expenses-postgres` | Headless | Governing service of the StatefulSet; gives the DB a stable DNS name. |
| Secret `expenses-db-credentials` | created by `scripts/deploy.sh`, outside Helm | Keeps the password out of git, values files and Helm release history. |
| NetworkPolicies | default-deny + 3 allow rules | Only the paths the app needs exist on the network. |

## Request path (user asks for the monthly summary)

1. `GET http://127.0.0.1:8082/api/summary?start=2026-10-01&end=2026-10-31` hits the kind node's published port, which maps to NodePort `30080`.
2. kube-proxy forwards to one **ready** endpoint of Service `expenses` (pods failing `/readyz` are not endpoints).
3. NetworkPolicy `expenses-api` admits TCP 8000. `RequestMiddleware` assigns `x-request-id`, starts the latency timer, and (if tracing is on) the OpenTelemetry span.
4. FastAPI validates the query parameters (dates, else `422`), and SQLAlchemy takes a pooled connection (`pool_pre_ping` discards dead ones).
5. The API connects to `expenses-postgres:5432`. Egress is allowed only to PostgreSQL, DNS and the tracing collector. PostgreSQL's policy admits only API pods.
6. `SELECT category, SUM(amount), COUNT(*) ... GROUP BY category` on `NUMERIC(12,2)` (exact money arithmetic, no floats), then `200` with totals as decimal strings. This is the most expensive query as data grows, which is why the dashboard shows p95 latency per route and the trace shows the SQL span separately. The middleware records `http_requests_total{route="/api/summary",status="200"}`, the latency histogram, `expenses_operations_total{operation="summary"}`, and one JSON access-log line.

## Commit-to-running path

```mermaid
flowchart LR
  c[git push<br/>commit SHA] --> q[quality<br/>ruff, pytest, pip-audit,<br/>hadolint, gitleaks,<br/>trivy config, helm lint,<br/>kubeconform, promtool]
  q --> b[build<br/>image :SHA<br/>trivy image scan]
  b --> d[deploy-test on kind<br/>helm --rollback-on-failure<br/>helm test, smoke, netpol,<br/>observability, bad-release,<br/>DB-fault, drift]
  b -->|push events| r1[(GHCR :SHA<br/>amd64+arm64,<br/>SBOM, provenance)]
  d --> rel{release<br/>environment: production<br/>manual approval}
  rel --> r2[(GHCR :release<br/>same digest)]
  r1 --> local[scripts/deploy.sh --tag SHA<br/>local kind]
```

The SHA is the single identifier throughout: git commit, image tag, OCI label `org.opencontainers.image.revision`, env `GIT_SHA` inside the container, pod label `app.kubernetes.io/version`, `/version` response, `x-app-version` header, and the Prometheus series `expenses_app_build_info{git_sha=...}`.

## Failure boundaries

| Failure | What happens | Why |
|---|---|---|
| One API pod crashes or hangs | Liveness fails, kubelet restarts it; Service routes to the other replica; PDB stops voluntary evictions dropping below 1. | Replicas + probes. |
| PostgreSQL down | `/readyz` returns 503, so all API pods leave the Service (fast failure, not timeouts). `/healthz` stays 200, so **no restart storm**. `ExpensesDatabaseUnreachable` pages. When the DB returns, pods turn ready on their own. Data stays on the PVC. | Liveness and readiness deliberately check different things. Demonstrated by `scripts/fault-demo.sh`. |
| Bad release (crashes, bad image, failing readiness) | New pod never turns ready, so `maxUnavailable: 0` keeps all old pods serving. Helm `--rollback-on-failure` reverts the release after the timeout. | Demonstrated by `scripts/release-demo.sh` (0 failed requests). |
| Node loss (multi-node) | API pods reschedule. Spread constraint prefers different nodes. PostgreSQL has RWO storage tied to a node, so the outage lasts until it reschedules. | Single DB replica is an accepted limitation. |
| Monitoring stack down | App unaffected (scraping is pull-based; OTLP export is async and drops on failure). | Telemetry is not on the request path. |

## Linux, networking and cloud concepts applied

- **Process model:** Uvicorn runs as PID 1 (exec-form `CMD`), so it receives SIGTERM directly. `preStop: sleep 5` lets endpoint removal propagate before shutdown, and `--timeout-graceful-shutdown 20` drains in-flight requests within `terminationGracePeriodSeconds: 30`.
- **Users and filesystem:** fixed UID 10001, no shell, code owned by root (read-only to the app), read-only root filesystem with a size-limited `emptyDir` at `/tmp`, all Linux capabilities dropped, seccomp `RuntimeDefault`.
- **Networking:** NodePort published on `127.0.0.1` only (not on the LAN), cluster DNS service discovery, headless service for stable DB naming, L3/L4 allow-listing with NetworkPolicy (ingress *and* egress).
- **Cloud mapping:** on a managed cluster the same chart would use an Ingress/Gateway with TLS instead of NodePort, a managed database (RDS/Cloud SQL) instead of the StatefulSet (`postgres.enabled=false`, `DB_HOST` pointing at the endpoint), and an external secrets operator instead of `kubectl create secret`.
