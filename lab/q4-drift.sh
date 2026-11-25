#!/usr/bin/env bash
# Q4 part 2: Argo CD reverting changes made outside Git (configuration drift).
set -euo pipefail
cd "$(dirname "$0")/.."
source lab/rec.sh evidence/logs/q4-gitops.log
status() { kubectl -n argocd get application textstats -o jsonpath='{.status.sync.status}/{.status.health.status}'; }
export -f status

rec kubectl -n argocd get application textstats -o jsonpath="'{.spec.syncPolicy}{\"\\n\"}'"
rec kubectl -n textstats get rollout text-stats

# drift 1: someone scales the app by hand
rec 'kubectl -n textstats scale rollout text-stats --replicas=3; echo "scaled by hand at $(date -u +%H:%M:%S)"'
rec 'for i in $(seq 1 30); do r=$(kubectl -n textstats get rollout text-stats -o jsonpath={.spec.replicas}); echo "$(date -u +%H:%M:%S) spec.replicas=$r app=$(status)"; [ "$r" = 10 ] && [ $i -gt 1 ] && break; sleep 1; done'

# drift 2: someone deletes the user-facing Service
rec 'kubectl -n textstats delete service text-stats; echo "deleted at $(date -u +%H:%M:%S)"'
rec 'until kubectl -n textstats get service text-stats >/dev/null 2>&1; do sleep 1; done; echo "recreated at $(date -u +%H:%M:%S)"; kubectl -n textstats get service text-stats'

rec kubectl -n argocd get application textstats -o jsonpath="'{range .status.history[*]}{.id}  {.revision}  {.deployedAt}{\"\\n\"}{end}'"
rec "kubectl -n argocd logs statefulset/argocd-application-controller --since=10m | jq -r 'select(.reason and (.msg | test(\"sync\"))) | .time + \"  \" + .msg' | tail -6"
