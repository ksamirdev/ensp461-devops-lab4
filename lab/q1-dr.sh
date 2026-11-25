#!/usr/bin/env bash
# Q1 part 2: disaster recovery drills on the live database while synthetic users keep writing.
#   1. on-demand base backup to the object store
#   2. failover: the primary pod is killed; measure how long writes fail
#   3. restore: an operator drops the table; recover it with point-in-time recovery from the object store
set -euo pipefail
cd "$(dirname "$0")/.."
source lab/rec.sh evidence/logs/q1-dr.log
NS="-n textstats"
primary() { kubectl $NS get cluster textstats-db -o jsonpath='{.status.currentPrimary}'; }
sql() { kubectl $NS exec "$1" -c postgres -- psql -U postgres -d textstats -Atc "$2"; }
probe() {  # probe <name> <seconds>: in-cluster writer measuring failed POST /stats requests
  kubectl $NS run "$1" --restart=Never --image=mirror.gcr.io/library/python:3.13-slim \
    -- python -c "$(cat lab/probe.py)" http://text-stats/stats "$2" post 4 >/dev/null
}
export -f primary sql; export NS

rec kubectl apply -f deploy/lab/traffic.yaml
rec kubectl $NS rollout status deploy/traffic --timeout=120s
rec kubectl $NS get cluster textstats-db -o wide
rec kubectl $NS get pods -l cnpg.io/cluster=textstats-db -L role
rec 'sql $(primary) "SELECT application_name, state, sync_state, replay_lag FROM pg_stat_replication"'
rec 'sql $(primary) "SELECT archived_count, last_archived_wal, last_archived_time, failed_count FROM pg_stat_archiver"'

# ---- 1. on-demand backup ----
rec "kubectl $NS apply -f - <<'YAML'
apiVersion: postgresql.cnpg.io/v1
kind: Backup
metadata:
  name: textstats-db-before-drills
spec:
  cluster: {name: textstats-db}
  method: plugin
  pluginConfiguration: {name: barman-cloud.cloudnative-pg.io}
YAML"
rec kubectl $NS wait backup/textstats-db-before-drills --for=jsonpath='{.status.phase}'=completed --timeout=300s
rec kubectl $NS get backup -o custom-columns=NAME:.metadata.name,PHASE:.status.phase,STARTED:.status.startedAt,STOPPED:.status.stoppedAt,BEGIN_WAL:.status.beginWal,END_WAL:.status.endWal
rec "kubectl -n backup exec deploy/seaweedfs -- sh -c 'echo fs.du /buckets/pg-backups/textstats-db | weed shell -master=localhost:9333' 2>&1 | tail -3"
rec "kubectl -n backup exec deploy/seaweedfs -- sh -c 'echo fs.ls /buckets/pg-backups/textstats-db/base | weed shell -master=localhost:9333' 2>&1 | tail -4"

# ---- 2. failover ----
rec 'echo "primary before: $(primary)"; sql $(primary) "SELECT count(*) FROM analyses"'
probe probe-failover 60
rec kubectl $NS wait pod/probe-failover --for=condition=Ready --timeout=120s
sleep 15
OLD=$(primary); export OLD
rec 'echo "killing primary $OLD at $(date -u +%H:%M:%S)"; kubectl $NS delete pod $OLD --grace-period=0 --force 2>&1 | grep -v Warning'
rec 'until [ "$(primary)" != "$OLD" ]; do sleep 0.5; done; echo "new primary $(primary) at $(date -u +%H:%M:%S)"'
rec "until [ \"\$(kubectl $NS get cluster textstats-db -o jsonpath='{.status.readyInstances}')\" = 2 ]; do sleep 2; done; echo \"both instances ready again at \$(date -u +%H:%M:%S); \$OLD rejoined as a replica\""
rec kubectl $NS get cluster textstats-db -o jsonpath="'{.status.currentPrimary} promoted, targetPrimaryTimestamp={.status.targetPrimaryTimestamp} currentPrimaryTimestamp={.status.currentPrimaryTimestamp}{\"\\n\"}'"
rec kubectl $NS wait pod/probe-failover --for=jsonpath='{.status.phase}'=Succeeded --timeout=120s
rec kubectl $NS logs probe-failover
kubectl $NS delete pod probe-failover >/dev/null
rec kubectl $NS get pods -l cnpg.io/cluster=textstats-db -L role
rec 'sql $(primary) "SELECT count(*) FROM analyses"'

# ---- 3. accidental DROP TABLE, recovered with point-in-time recovery ----
rec 'sql $(primary) "SELECT count(*) AS rows, max(id) AS last_id, pg_current_wal_lsn() AS lsn, now() FROM analyses" | tee /tmp/q1-before-drop'
LSN=$(cut -d'|' -f3 /tmp/q1-before-drop)
rec 'sql $(primary) "BEGIN; LOCK analyses; SELECT max(id) AS last_id_at_drop FROM analyses; DROP TABLE analyses; COMMIT" | grep -v -E "^(BEGIN|LOCK|DROP|COMMIT)"; echo "table dropped at $(date -u +%H:%M:%S)"'
rec 'sql $(primary) "SELECT pg_switch_wal()"'   # close the WAL segment so the drop and everything before it is archived now
rec "sleep 8; kubectl $NS exec deploy/traffic -- curl -s -X POST -H 'Content-Type: application/json' -d '{\"text\":\"after the drop\"}' http://text-stats/stats; echo"
rec 'sql $(primary) "SELECT last_archived_wal, last_archived_time FROM pg_stat_archiver"'
START=$(date +%s)
rec "sed 's|TARGET_LSN|$LSN|' deploy/dr/restore-cluster.yaml | kubectl apply -f -"
rec "until [ \"\$(kubectl $NS get cluster textstats-db-restore -o jsonpath='{.status.phase}' 2>/dev/null)\" = 'Cluster in healthy state' ]; do sleep 3; done; echo restore cluster healthy after \$((\$(date +%s) - $START)) s"
rec 'sql textstats-db-restore-1 "SELECT count(*) AS rows, max(id) AS last_id FROM analyses"'
# copy the recovered table back into the live primary; the app's writes start succeeding again
rec "kubectl $NS exec textstats-db-restore-1 -c postgres -- pg_dump -U postgres -d textstats -t analyses | kubectl $NS exec -i \$(primary) -c postgres -- psql -U postgres -d textstats -q && echo table restored into \$(primary) after \$((\$(date +%s) - $START)) s"
rec 'sql $(primary) "ALTER TABLE analyses OWNER TO textstats"'
rec "sleep 5; sql \$(primary) \"SELECT count(*) AS rows, max(id) AS last_id, count(*) FILTER (WHERE id > $(cut -d'|' -f2 /tmp/q1-before-drop)) AS written_after_restore FROM analyses\""
rec kubectl $NS delete cluster textstats-db-restore
