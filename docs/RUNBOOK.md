# Runbook

## What "healthy" means

| Signal | Healthy | Where to look |
|---|---|---|
| User success | `scripts/smoke-test.sh` passes (record three expenses, summary totals are exactly right (115.00), date + category filter, zero amount 422, delete, totals back to 0.00) | terminal / CI step |
| Availability SLI | `1 - expenses:api_error_ratio:rate30m` >= 99.5% | Grafana "Expenses - Service Health", top-left |
| Latency SLI | `expenses:api_latency_good_ratio:rate5m` >= 95% under 300 ms | Grafana, top row |
| Capacity | ready API pods >= 2, `expenses_db_up == 1` | Grafana, `kubectl -n expenses get pods` |
| Version | `/version` `git_sha` equals the intended commit | `curl 127.0.0.1:8082/version` |

SLO window: 30 days. Error budget: 0.5% of SLO-route requests (about 3.6 h of full outage per 30 days).

## General investigation flow

1. **Symptom:** which alert, what users see (`curl -i 127.0.0.1:8082/api/expenses`).
2. **Scope:** `kubectl -n expenses get pods,deploy,sts -o wide` and `kubectl -n expenses get events --sort-by=.lastTimestamp | tail`.
3. **Change?** `helm -n expenses history expenses`. Did a release just happen? Compare `/version` with the expected SHA.
4. **Evidence:** logs `kubectl -n expenses logs deploy/expenses --tail=100 | grep -v '"status": 2'`, take a `trace_id`, open it in Jaeger (127.0.0.1:16688).
5. **Act**, then **verify recovery** with the same signal that alerted (alert resolves) *and* the user signal (`scripts/smoke-test.sh`).

---

## ExpensesApiErrorBudgetFastBurn
*Page. More than 7.2% of SLO-route requests are failing (14.4x the budget) over both 1h and 5m.*

- If a release went out in the last hour: roll back first, investigate second. Run `helm -n expenses rollback expenses` (previous revision) and confirm `/version`.
- Otherwise, check whether `ExpensesDatabaseUnreachable` is also firing. If so, follow that entry.
- Look for the failing route: Grafana panel "Request rate by route and status", or `sum by (route,status)(rate(http_requests_total{status=~"5.."}[5m]))`.
- Grep logs for `"status": 5` and follow the trace.
- **Verify:** the 5m error ratio is back under 0.5% and the smoke test passes. The alert clears quickly because its 5m window drops first.

## ExpensesApiErrorBudgetSlowBurn
*Ticket. A steady error rate above 3% over 6h.* Usually one route or one input failing persistently. Find the route as above and fix it in code. No rollback unless it correlates with a release.

## ExpensesApiLatencySLOBreach
*Ticket. Fewer than 95% of SLO-route requests finish within 300 ms for 10 minutes.*

- Check the p95/p99 panel and pod CPU. Throttling at the 500m limit shows as CPU flat at the limit.
- Check whether the HPA is at max: `kubectl -n expenses get hpa`.
- Open a slow trace in Jaeger. Is the time in the SQL span (DB) or in the handler?
- Mitigate by scaling (`kubectl -n expenses scale deploy/expenses --replicas=4`, temporary; then make it permanent in values and redeploy).

## ExpensesApiDown
*Page. No API pod has been scraped successfully for 2 minutes.*

- `kubectl -n expenses get pods -l app.kubernetes.io/component=api`. Look for CrashLoopBackOff, ImagePullBackOff or Pending.
- ImagePullBackOff after a deploy means the wrong tag or a private GHCR package. Run `helm rollback`.
- CrashLoopBackOff: `kubectl -n expenses logs <pod> --previous`.
- Pending: `kubectl describe pod`, usually resources or PVC.
- If the pods are fine, it is a scrape problem. Check the Prometheus targets page (127.0.0.1:9092/targets) and the NetworkPolicy.

## ExpensesDatabaseUnreachable
*Page. Every API pod's readiness check fails to reach PostgreSQL.*

Expected behaviour during this incident: API pods are **NotReady but not restarting**, and requests fail fast instead of hanging.

- `kubectl -n expenses get sts,pods -l app.kubernetes.io/component=database`
- `kubectl -n expenses logs sts/expenses-postgres --tail=50`. Watch for disk full, auth errors, or crash recovery in progress.
- `kubectl -n expenses get pvc` should show the PVC Bound.
- If the StatefulSet was scaled down or the pod deleted, `kubectl -n expenses scale sts/expenses-postgres --replicas=1`.
- **Verify:** `kubectl -n expenses rollout status deploy/expenses`, `/readyz` returns `database: up`, data written before the outage is still listed, and the alert resolves. `scripts/fault-demo.sh` rehearses exactly this.

## ExpensesPodRestartingOften
*Ticket. A pod restarted more than twice in 15 minutes.*

- `kubectl -n expenses describe pod <pod>` and read Last State. `OOMKilled` means raise the memory limit or find the leak. An exit code with a logged traceback means an app bug.
- Liveness failures without crashes: check whether `/healthz` is slow (CPU throttling) before loosening probe timeouts.

---

## Routine operations

| Task | Command |
|---|---|
| Deploy a CI-built commit | `scripts/deploy.sh --tag <sha>` |
| Roll back to the previous release | `helm -n expenses rollback expenses` then `scripts/smoke-test.sh` |
| Roll back to a specific revision | `helm -n expenses history expenses`, then `helm -n expenses rollback expenses <rev>` |
| Detect manual changes (drift) | `scripts/drift-check.sh` (fix by redeploying from git, never by hand) |
| Rotate the DB password | `ALTER USER expenses PASSWORD '...'` in Postgres, update the Secret, then `kubectl -n expenses rollout restart deploy/expenses` |
