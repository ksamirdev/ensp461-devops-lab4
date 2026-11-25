#!/usr/bin/env bash
# Q7: follow a canary release that was started by a commit to deploy/gitops on main.
#   lab/q7-canary.sh <name>   (name labels the screenshots, e.g. good or bad)
set -euo pipefail
cd "$(dirname "$0")/.."
source lab/rec.sh evidence/logs/q7-canary.log
NAME=$1; SHOTS=evidence/screenshots
kubectl -n monitoring port-forward svc/prometheus-server 19090:80 >/dev/null 2>&1 &
PF=$!
kubectl argo rollouts dashboard -n textstats -p 3100 >/dev/null 2>&1 &
DASH=$!
trap 'kill $PF $DASH' EXIT
shot() {  # the dashboard streams its data, so use a real browser session and wait for it to render
  agent-browser set viewport 1500 1000 >/dev/null 2>&1; agent-browser open "$2" >/dev/null 2>&1
  agent-browser wait 4000 >/dev/null 2>&1; agent-browser screenshot "$SHOTS/$1.png" >/dev/null 2>&1 || true; }
DASHBOARD=http://localhost:3100/rollouts/rollout/textstats/text-stats
prom() { curl -s --data-urlencode "query=$1" http://127.0.0.1:19090/api/v1/query | jq -r '.data.result[] | "\(.metric.rollouts_pod_template_hash // "-")  \(.value[1])"'; }
export -f prom

SHA=$(git rev-parse origin/main)
rec git log -1 --format="'%h %ad %s'" --date=format:%H:%M:%S origin/main
rec git show --stat --format= origin/main -- deploy/gitops
rec "until [ \"\$(kubectl -n argocd get application textstats -o jsonpath='{.status.sync.revision}')\" = $SHA ]; do sleep 2; done; echo \"Argo CD synced ${SHA:0:7} at \$(date -u +%H:%M:%S) without a manual sync\""

# screenshot the dashboard while the first canary pod is live (step 1 = paused at 10%)
( until kubectl -n textstats get rollout text-stats -o jsonpath='{.status.currentStepIndex} {.status.phase}' | grep -qE '^2 |Degraded'; do sleep 2; done
  shot "q7-$NAME-canary-10" "$DASHBOARD" ) &
SNAP=$!
# one line per change of step, phase or pod split until the rollout settles
rec 'last=""; while :; do
  s=$(kubectl -n textstats get rollout text-stats -o jsonpath="step={.status.currentStepIndex} phase={.status.phase} new_version_pods={.status.updatedReplicas} ready={.status.readyReplicas} {.status.message}")
  [ "$s" != "$last" ] && echo "$(date -u +%H:%M:%S) $s" && last=$s
  case "$s" in *"phase=Healthy"*|*"phase=Degraded"*) break;; esac
  sleep 2; done'
wait $SNAP || true
shot "q7-$NAME-dashboard" "$DASHBOARD"
rec kubectl argo rollouts get rollout text-stats -n textstats --no-color
rec kubectl -n textstats get analysisrun --sort-by=.metadata.creationTimestamp
rec "kubectl -n textstats get analysisrun --sort-by=.metadata.creationTimestamp -o json | jq -r '.items[-3:][] | .metadata.name as \$n | .status.metricResults[] | \"\(\$n)  \(.name)  phase=\(.phase)  values=\([.measurements[].value] | join(\" \"))\"'"
rec 'echo "requests/s per pod-template hash:"; prom "sum by (rollouts_pod_template_hash) (rate(textstats_http_requests_total{route=\"/stats\"}[1m]))"'
rec 'echo "5xx share per pod-template hash:"; prom "sum by (rollouts_pod_template_hash) (rate(textstats_http_requests_total{route=\"/stats\",status=~\"5..\"}[2m])) / sum by (rollouts_pod_template_hash) (rate(textstats_http_requests_total{route=\"/stats\"}[2m]))"'
rec kubectl -n argocd get application textstats
