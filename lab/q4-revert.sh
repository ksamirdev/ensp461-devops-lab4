#!/usr/bin/env bash
# Q4 part 3: rollback through Git. A revert commit on main is the only action; Argo CD does the rest.
set -euo pipefail
cd "$(dirname "$0")/.."
source lab/rec.sh evidence/logs/q4-gitops.log
SHA=$(git rev-parse origin/main)
rec git log --oneline -4 origin/main
rec git show --format="'%h %ad %s'" --date=format:%H:%M:%S origin/main -- deploy/gitops '|' head -20
rec kubectl -n argocd get application textstats
rec "until [ \"\$(kubectl -n argocd get application textstats -o jsonpath='{.status.sync.revision}')\" = $SHA ]; do sleep 2; done; echo \"Argo CD synced ${SHA:0:7} at \$(date -u +%H:%M:%S)\""
rec "until [ \"\$(kubectl -n argocd get application textstats -o jsonpath='{.status.health.status}')\" = Healthy ]; do sleep 2; done; echo \"application Healthy at \$(date -u +%H:%M:%S)\""
rec kubectl -n argocd get application textstats
rec kubectl argo rollouts get rollout text-stats -n textstats --no-color '|' head -12
rec kubectl -n argocd get application textstats -o jsonpath="'{range .status.history[*]}{.id}  {.revision}  {.deployedAt}{\"\\n\"}{end}'"
rec "kubectl -n argocd logs statefulset/argocd-application-controller --since=20m | jq -r 'select(.reason and (.msg | test(\"sync\"))) | .time + \"  \" + .msg' | grep -E 'Initiated|succeeded' | tail -8"
