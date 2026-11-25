#!/usr/bin/env bash
# Q3: blue-green release of 4.0.0 (blue) -> 4.0.1 (green) with a probe measuring every request during the switch.
set -euo pipefail
cd "$(dirname "$0")/.."
source lab/rec.sh evidence/logs/q3-bluegreen.log
NS="-n bluegreen"; export NS
probe() {  # probe <name> <seconds>: in-cluster client recording which colour answered each request
  kubectl $NS run "$1" --restart=Never --image=mirror.gcr.io/library/python:3.13-slim \
    -- python -c "$(cat lab/probe.py)" http://text-stats/ "$2" get 8 >/dev/null
  kubectl $NS wait pod/"$1" --for=condition=Ready --timeout=120s >/dev/null
}
switch() { kubectl $NS patch service text-stats -p "{\"spec\":{\"selector\":{\"app\":\"text-stats\",\"color\":\"$1\"}}}"; }
export -f switch

# 1. blue is live
rec kubectl create namespace bluegreen --dry-run=client -o yaml '|' kubectl apply -f -
rec kubectl apply -f deploy/bluegreen/blue.yaml -f deploy/bluegreen/services.yaml
kubectl $NS run client --image=curlimages/curl:8.23.0 --command -- sleep infinity >/dev/null
kubectl $NS wait pod/client --for=condition=Ready --timeout=120s >/dev/null
rec kubectl $NS rollout status deploy/text-stats-blue --timeout=180s
rec kubectl $NS exec client -- curl -s http://text-stats/

# 2. green is deployed next to it and tested through the preview Service, with no user traffic
rec kubectl apply -f deploy/bluegreen/green.yaml
rec kubectl $NS rollout status deploy/text-stats-green --timeout=180s
rec kubectl $NS get pods -L color -o wide
rec kubectl $NS exec client -- curl -s --retry 5 --retry-connrefused http://text-stats-preview/
rec kubectl $NS exec client -- curl -s -X POST -H "'Content-Type: application/json'" -d "'{\"text\":\"green preview check\"}'" http://text-stats-preview/stats
rec kubectl $NS exec client -- curl -s http://text-stats/
rec kubectl $NS get endpointslices -L kubernetes.io/service-name

# 3. switch: one selector change, measured by 8 concurrent clients
probe probe-switch 40
sleep 20
rec 'switch green; echo "switched to green at $(date -u +%H:%M:%S)"'
rec kubectl $NS wait pod/probe-switch --for=jsonpath='{.status.phase}'=Succeeded --timeout=120s
rec kubectl $NS logs probe-switch
kubectl $NS delete pod probe-switch >/dev/null

# 4. rollback: blue is still running, so going back is the same one-line change
probe probe-rollback 30
sleep 15
rec 'switch blue; echo "rolled back to blue at $(date -u +%H:%M:%S)"'
rec kubectl $NS wait pod/probe-rollback --for=jsonpath='{.status.phase}'=Succeeded --timeout=120s
rec kubectl $NS logs probe-rollback
kubectl $NS delete pod probe-rollback >/dev/null

# 5. final cut-over; blue is scaled to zero once green has proven itself, keeping its spec for the next release
rec 'switch green && kubectl $NS scale deploy/text-stats-blue --replicas=0'
rec kubectl $NS get deploy,svc -o wide
rec kubectl $NS exec client -- curl -s http://text-stats/
kubectl $NS delete pod client --wait=false >/dev/null
