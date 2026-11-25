#!/usr/bin/env bash
# Q6 part 2: safe handling of credentials - nothing in Git, least privilege, audit trail, rotation.
# Secret values are only ever compared by fingerprint (first 12 hex chars of SHA-256); none is printed.
set -euo pipefail
cd "$(dirname "$0")/.."
source lab/rec.sh evidence/logs/q6-vault.log
kubectl -n vault port-forward pod/vault-0 18200:8200 >/dev/null 2>&1 &
PF=$!
trap 'kill $PF' EXIT
export VAULT_ADDR=http://127.0.0.1:18200
until curl -s -o /dev/null $VAULT_ADDR/v1/sys/health; do sleep 1; done
fp() { shasum -a 256 | cut -c1-12; }
vault_fp() { VAULT_TOKEN=$(jq -r .root_token .vault-init.json) vault kv get -field=password secret/textstats/db | fp; }
k8s_fp() { kubectl -n textstats get secret textstats-db-credentials -o jsonpath='{.data.password}' | base64 -d | fp; }
# app pods created after time $1 that are ready and not terminating, and all app pods
restarted() { kubectl -n textstats get pods -l app=text-stats -o json | jq --arg t "$1" '[.items[] | select(.metadata.creationTimestamp >= $t and .metadata.deletionTimestamp == null and .status.containerStatuses[0].ready)] | length'; }
pods() { kubectl -n textstats get pods -l app=text-stats --no-headers | wc -l | tr -d ' '; }
export -f fp vault_fp k8s_fp restarted pods

# 1. where the credential lives, and where it does not
rec kubectl -n textstats get externalsecret
rec kubectl -n textstats get secret textstats-db-credentials -o jsonpath="'{.type}  owner={.metadata.ownerReferences[0].kind}/{.metadata.ownerReferences[0].name}  keys={.data}{\"\\n\"}'" '|' sed -E "'s/\"[A-Za-z0-9+\/=]{16,}\"/<redacted>/g'"
rec 'echo "vault: $(vault_fp)   kubernetes secret: $(k8s_fp)"'
rec 'P=$(kubectl -n textstats get secret textstats-db-credentials -o jsonpath={.data.password} | base64 -d); echo "occurrences of the live password in all git history: $(git log -p --all | grep -cF "$P" || true)"'
rec grep -rn "password" deploy/gitops '|' grep -v "^\s*#" '|' head -5
rec "docker run --rm -v \$PWD:/repo ghcr.io/gitleaks/gitleaks:v8.30.1 git /repo --redact --no-banner 2>&1 | tail -2"

# 2. least privilege: log in exactly as External Secrets does, with the textstats service account
rec 'JWT=$(kubectl -n textstats create token textstats-secrets --audience vault --duration 10m)
  export VAULT_TOKEN=$(vault write -field=token auth/kubernetes/login role=textstats jwt="$JWT")
  vault token lookup -format=json | jq -c ".data | {display_name, policies, ttl}"
  echo "--- read own database login:"; vault kv get -field=username secret/textstats/db; echo
  echo "--- read backup admin keys:"; vault kv get secret/backup/seaweedfs-admin 2>&1 | grep -E "Code|permission" | head -2
  echo "--- overwrite own secret:"; vault kv put secret/textstats/db password=x 2>&1 | grep -E "Code|permission" | head -2'

# 3. audit trail: every access is logged, with secret values HMAC-ed
rec "kubectl -n vault exec vault-0 -- cat /vault/audit/audit.log | jq -c 'select(.type==\"response\" and (.request.path | test(\"secret/data/(textstats|backup)\"))) | {time, who: .auth.display_name, op: .request.operation, path: .request.path, error, password: .response.data.data.password}' | tail -6"

# 4. rotation: new password in Vault -> Kubernetes Secret -> PostgreSQL role -> app pods, under live traffic
export OLD=$(VAULT_TOKEN=$(jq -r .root_token .vault-init.json) vault kv get -field=password secret/textstats/db)
export VAULT_TOKEN=$(jq -r .root_token .vault-init.json)
kubectl -n textstats run probe-rotation --restart=Never --image=mirror.gcr.io/library/python:3.13-slim \
  -- python -c "$(cat lab/probe.py)" http://text-stats/stats 180 post 4 >/dev/null
kubectl -n textstats wait pod/probe-rotation --for=condition=Ready --timeout=120s >/dev/null
sleep 10
rec 'vault kv put secret/textstats/db username=textstats password=$(openssl rand -hex 20) | grep -E "^(version|created_time)"; echo "rotated in Vault at $(date -u +%H:%M:%S), fingerprint now $(vault_fp)"'
rec 'kubectl -n textstats annotate externalsecret textstats-db-credentials textstats-database-url force-sync=$(date +%s) --overwrite'
rec 'until [ "$(k8s_fp)" = "$(vault_fp)" ]; do sleep 1; done; echo "kubernetes secret updated at $(date -u +%H:%M:%S)"'
rec 'T=$(date -u +%Y-%m-%dT%H:%M:%SZ); kubectl argo rollouts restart text-stats -n textstats
  until [ "$(restarted $T)" = 10 ] && [ "$(pods)" = 10 ]; do sleep 2; done; echo "all 10 app pods replaced and ready with the new secret at $(date -u +%H:%M:%S)"'
rec kubectl -n textstats wait pod/probe-rotation --for=jsonpath='{.status.phase}'=Succeeded --timeout=300s
rec kubectl -n textstats logs probe-rotation '|' grep -vE "'^ +[0-9]+  write-ok=[0-9]+$'"
kubectl -n textstats delete pod probe-rotation >/dev/null
rec 'P=$(kubectl -n textstats get cluster textstats-db -o jsonpath={.status.currentPrimary})
  echo -n "old password: "; kubectl -n textstats exec $P -c postgres -- psql "postgresql://textstats:$OLD@textstats-db-rw/textstats" -Atc "SELECT 1" 2>&1 | grep -oE "password authentication failed[^,]*|^1$"
  NEW=$(kubectl -n textstats get secret textstats-db-credentials -o jsonpath={.data.password} | base64 -d)
  echo -n "new password: "; kubectl -n textstats exec $P -c postgres -- psql "postgresql://textstats:$NEW@textstats-db-rw/textstats" -Atc "SELECT current_user"'
rec vault kv metadata get secret/textstats/db '|' grep -E "'^(current_version|created_time|updated_time)'"
