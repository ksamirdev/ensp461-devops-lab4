# ENSP461 Lab 4 - Advanced Deployment Strategies & Enterprise DevOps

Author: Samir Kumar Gupta (Roll No. 2301730243)

The text statistics service from Lab 3, now backed by PostgreSQL and released with enterprise deployment practices.
A GitHub Actions pipeline gates every image on unit, integration and staging smoke tests.
Argo CD keeps the cluster equal to this repository, Argo Rollouts releases new versions as canaries checked against Prometheus, and Vault holds every credential.
The database has a streaming replica, continuous WAL archiving and point-in-time recovery from object storage.

## Reports

One PDF per question in [`reports/`](reports/):

| Question | Report |
|---|---|
| Q1 Disaster recovery (backup, restore, failover) | [q1-disaster-recovery.pdf](reports/q1-disaster-recovery.pdf) |
| Q2 Automated testing as CI/CD pipeline gates | [q2-cicd-test-gates.pdf](reports/q2-cicd-test-gates.pdf) |
| Q3 Blue-Green deployment | [q3-blue-green.pdf](reports/q3-blue-green.pdf) |
| Q4 GitOps-based delivery | [q4-gitops.pdf](reports/q4-gitops.pdf) |
| Q5 Advanced deployment strategies report | [q5-advanced-deployment-report.pdf](reports/q5-advanced-deployment-report.pdf) |
| Q6 Secret management | [q6-secret-management.pdf](reports/q6-secret-management.pdf) |
| Q7 Canary deployment | [q7-canary.pdf](reports/q7-canary.pdf) |

Every command output in the reports is copied from the logs in [`evidence/logs/`](evidence/logs/), which `lab/rec.sh` recorded while the commands ran.
Screenshots are in [`evidence/screenshots/`](evidence/screenshots/).
`python3 lab/build_reports.py` rebuilds the PDFs from that evidence.

## Results at a glance

- Q1: the primary was killed under load and a replica was promoted 4 s later; writes failed for 4.79 s (108 of 7252 requests).
- Q1: a dropped table was recovered by point-in-time restore from object storage in 65 s, losing 2 rows.
- Q2: a commit with a failing regression test was stopped at the integration tests, so no image was built or published.
- Q3: blue-green switch and rollback with 0 failed requests out of 13301 and 9461.
- Q4: a manual scale was reverted by Argo CD in about 3 s, a deleted Service came back in 4 s, and a Git revert was Healthy 3 s after sync.
- Q6: no secret in Git history (gitleaks clean), 403 on paths outside a namespace's policy, and a rotation that reached all 10 pods in 13 s with 213 of 19775 writes failing during the switch.
- Q7: release 4.0.1 passed three canary analyses with 0 errors; a faulty build (27% errors) was aborted automatically while on 1 of 10 pods.

## Layout

- `service/` - Flask app: `/stats` (stored in PostgreSQL), `/analyses`, `/healthz`, `/readyz`, `/metrics`, and `FAULT_RATE` fault injection
- `tests/unit/` - pytest unit tests, no database
- `tests/integration/` - tests against a real PostgreSQL server (`DATABASE_URL`)
- `tests/smoke/` - tests against a deployed Service (`BASE_URL`)
- `.github/workflows/` - the CI/CD pipeline (Q2)
- `deploy/platform/` - Helm values for Vault and Prometheus
- `deploy/gitops/` - everything Argo CD applies to the `textstats` namespace: database, ExternalSecrets, canary Rollout (Q1, Q4, Q6, Q7)
- `deploy/argocd/` - the Argo CD Application (Q4)
- `deploy/backup/` - SeaweedFS S3 object store for database backups (Q1)
- `deploy/dr/` - point-in-time recovery cluster (Q1)
- `deploy/bluegreen/` - blue and green Deployments and the switching Service (Q3)
- `deploy/staging/` - the throwaway staging environment the pipeline deploys to (Q2)
- `deploy/lab/` - synthetic user traffic
- `lab/` - platform install, one recorded script per question, in-cluster availability probe, report builder
- `evidence/` - command logs and screenshots

## Environment

Everything ran on the Kubernetes cluster built into OrbStack on macOS (single node, v1.36, arm64), with 8 GB of memory and 6 CPUs.
The pipeline runs on GitHub's arm64 runners, so the image it publishes runs on the lab cluster unchanged.
CLIs used: kubectl 1.37, helm 4.3, argocd 3.6, kubectl-argo-rollouts 1.10, vault 2.2, gh and gitleaks.

`lab/platform.sh` installs, each at a pinned version:

- cert-manager v1.21.3
- CloudNativePG 1.30.2 with the Barman Cloud plugin v0.16.0
- Argo CD v3.6.3 and Argo Rollouts v1.10.2
- External Secrets 2.15.0
- Prometheus (chart 30.0.1)
- Vault (chart 0.34.1)

## Running each part

Run these from the repository root with the cluster as the current kubectl context.

```
bash lab/platform.sh          # platform components
bash lab/q6-vault.sh          # Q6: init and unseal Vault, store generated secrets, policies, Kubernetes auth
bash lab/q1-backup-store.sh   # Q1: SeaweedFS object store and the pg-backups bucket
bash lab/q4-bootstrap.sh      # Q4: Argo CD application; builds the textstats namespace from Git
bash lab/q1-dr.sh             # Q1: on-demand backup, primary failover under load, point-in-time restore
bash lab/q2-runs.sh <run-id>  # Q2: record a pipeline run
bash lab/q3-bluegreen.sh      # Q3: blue-green switch and rollback, measured by an in-cluster probe
bash lab/q4-drift.sh          # Q4: manual changes reverted by Argo CD self-heal
bash lab/q7-canary.sh good    # Q7: follow a canary, run after a release commit to deploy/gitops (good or bad)
bash lab/q4-revert.sh         # Q4: rollback through Git, run after a revert commit on main
bash lab/q6-rotation.sh       # Q6: no secrets in Git, least privilege, audit log, password rotation under load
```

`lab/probe.py` is the in-cluster availability probe the drills use.
It runs as a pod and reports every second's outcomes:

```
kubectl run probe --rm -i --restart=Never --image=mirror.gcr.io/library/python:3.13-slim -- \
    python -c "$(cat lab/probe.py)" http://text-stats/ 40 get 8
```

Vault's unseal keys and root token are written to `.vault-init.json`, which is gitignored and mode 600.
No secret value is stored in this repository; gitleaks checks the whole history in every pipeline run.

## Pipeline

Every push to `main` and every pull request runs:

secret scan + unit tests -> integration tests (PostgreSQL) -> build -> deploy to kind staging + smoke tests -> publish to GHCR

Each job runs only if the jobs before it passed, so a failure anywhere stops the image from being published.
Run 45645419739 was blocked at the integration tests by a real concurrency bug, and the fix in run 45647118437 passed every gate.
The details are in the Q2 report.
