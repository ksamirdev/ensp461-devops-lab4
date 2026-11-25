#!/usr/bin/env bash
# Q4 part 1: register the Git repository with Argo CD and let it build the textstats namespace from Git.
set -euo pipefail
cd "$(dirname "$0")/.."
source lab/rec.sh evidence/logs/q4-gitops.log
app() { kubectl -n argocd get application textstats -o jsonpath='{.status.sync.status} {.status.health.status} {.status.sync.revision}'; }

rec git log --oneline -1 origin/main
rec kubectl get namespace textstats '||' true
rec kubectl apply -f deploy/argocd/textstats.yaml
rec "until [ \"\$(kubectl -n argocd get application textstats -o jsonpath='{.status.sync.status} {.status.health.status}')\" = 'Synced Healthy' ]; do sleep 5; done; echo synced and healthy after \$SECONDS s"
rec kubectl -n argocd get application textstats -o wide
rec kubectl -n textstats get cluster,objectstore,scheduledbackup,externalsecret,rollout,svc
rec kubectl -n textstats get pods -o wide
