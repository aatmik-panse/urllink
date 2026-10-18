# Evidence

Evidence is produced by running the system, not by screenshots alone. Every claim below maps to a check that **fails the pipeline** if the behaviour is wrong.

## Where to find it

1. **CI run for the final commit.** Open the PR's *Checks* tab, then the *CI/CD* run. The run summary shows the image SHA/digest and the evidence bundle. The `evidence-<sha>` artifact contains `EVIDENCE.md`, the live Deployment YAML, pod descriptions, events and API logs captured from the cluster that ran the tests.
2. **Local run** (my laptop, same scripts): see the PR description for the dashboard/Jaeger screenshots and terminal output.

## Claim to proof

| Claim | Check (script / CI step) | What proves it |
|---|---|---|
| The tested commit is the one running | `smoke-test.sh <sha>`, `observability-check.sh <sha>`, `collect-evidence.sh` | `/version.git_sha == <sha>`; pod label `app.kubernetes.io/version=<sha>`; `expenses_app_build_info{git_sha=<sha>}` in Prometheus; running image digest |
| Users can use the app | `helm test`, `smoke-test.sh` | record three expenses, summary totals are exactly right (115.00), date + category filter, zero amount 422, delete, totals back to 0.00; through the Service (NodePort) and from inside the cluster |
| Pipeline checks code and config | job `quality` | ruff, all unit tests, pip-audit, hadolint, gitleaks, trivy config, kubeconform (48 resources), promtool rule tests |
| Image is scanned and hardened | job `build` | trivy image scan gate; `Config.User == 10001:10001` |
| Bad releases don't reach users | `release-demo.sh` | broken tag is rejected, release auto-rolled back, version unchanged, **0 non-200 responses** across the whole bad rollout |
| DB outage is contained and self-heals | `fault-demo.sh` | readiness 503 + pods NotReady, `ExpensesDatabaseUnreachable` **fires**; after recovery readiness returns without intervention, pre-outage data still present, **0 API restarts**, alert **resolves** |
| Alert logic is correct | `promtool test rules` | healthy traffic: no alerts; 50% errors: fast-burn page; DB down: page; no targets: page; slow responses: latency ticket |
| NetworkPolicies are enforced | `verify-netpol.sh` | unrelated pod blocked from PostgreSQL; API reaches PostgreSQL; API blocked from the internet |
| Monitoring is wired, not just declared | `observability-check.sh` | every API pod scraped; SLO rules loaded; SLIs computed from live traffic; no alerts firing when healthy |
| No configuration drift | `drift-check.sh` | every field the release declares matches the live object; release == chart in git |
| Secrets stay out of the repo and evidence | gitleaks; `collect-evidence.sh` | full-history scan clean; evidence lists Secret names only |

## Local capture (for the viva)

```bash
scripts/cluster-up.sh && scripts/deploy.sh --tag <sha>
scripts/smoke-test.sh <sha> | tee evidence-local.txt
scripts/release-demo.sh | tee -a evidence-local.txt
WAIT_FOR_ALERT=1 scripts/fault-demo.sh | tee -a evidence-local.txt
scripts/collect-evidence.sh
```

Screenshots worth adding to the PR: the Grafana dashboard during `fault-demo.sh` (availability drop, DB DOWN, recovery), Prometheus *Alerts* with `ExpensesDatabaseUnreachable` firing, a Jaeger trace of `POST /api/expenses` showing the SQL span, and the Actions run graph with the approved `release` job.
