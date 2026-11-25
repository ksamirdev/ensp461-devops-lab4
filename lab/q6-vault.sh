#!/usr/bin/env bash
# Q6: initialise, unseal and configure Vault, then wire External Secrets to it.
# Unseal keys and the root token go only to .vault-init.json (gitignored, mode 600) and are never printed.
# Every generated password goes straight from openssl into Vault; none is echoed or written to disk.
set -euo pipefail
cd "$(dirname "$0")/.."
source lab/rec.sh evidence/logs/q6-vault.log
# Talk to the pod directly: the vault Service has no endpoints while Vault is sealed (not ready)
kubectl -n vault port-forward pod/vault-0 18200:8200 >/dev/null 2>&1 &
trap 'kill $!' EXIT
export VAULT_ADDR=http://127.0.0.1:18200
until curl -s -o /dev/null $VAULT_ADDR/v1/sys/health; do sleep 1; done
INIT=.vault-init.json

rec kubectl -n vault get pods
rec vault status '|' grep -E "'^(Initialized|Sealed|Storage Type|Version)'" '||' true

if [ ! -s "$INIT" ]; then
  # 5 key shares, any 3 unseal: no single person can unseal Vault alone
  rec "umask 077 && vault operator init -key-shares=5 -key-threshold=3 -format=json > $INIT && echo 'unseal keys and root token written to $INIT (mode 600, gitignored)'"
fi
rec ls -l $INIT
rec git check-ignore -v $INIT
for i in 0 1 2; do
  rec "vault operator unseal \$(jq -r '.unseal_keys_b64[$i]' $INIT) | grep -E '^(Sealed|Unseal Progress)'"
done
rec vault status '|' grep -E "'^(Initialized|Sealed|Total Shares|Threshold)'"

export VAULT_TOKEN=$(jq -r .root_token $INIT)

rec "vault audit list 2>/dev/null | grep -q '^file/' || vault audit enable file file_path=/vault/audit/audit.log"
rec "vault secrets list | grep -q '^secret/' || vault secrets enable -path=secret -version=2 kv"
rec "vault kv get secret/textstats/db >/dev/null 2>&1 || vault kv put secret/textstats/db username=textstats password=\$(openssl rand -hex 20) >/dev/null && echo stored secret/textstats/db"
rec "vault kv get secret/backup/pg-backup >/dev/null 2>&1 || vault kv put secret/backup/pg-backup access_key=pg-backup-\$(openssl rand -hex 4) secret_key=\$(openssl rand -hex 24) >/dev/null && echo stored secret/backup/pg-backup"
rec "vault kv get secret/backup/seaweedfs-admin >/dev/null 2>&1 || vault kv put secret/backup/seaweedfs-admin access_key=admin-\$(openssl rand -hex 4) secret_key=\$(openssl rand -hex 24) >/dev/null && echo stored secret/backup/seaweedfs-admin"
rec vault kv list secret/textstats
rec vault kv list secret/backup
rec vault kv metadata get secret/textstats/db '|' grep -E "'^(created_time|current_version|max_versions)'"

# Least privilege: each namespace's reader can read only its own paths
rec "vault policy write textstats-read - <<'HCL'
path \"secret/data/textstats/*\"      { capabilities = [\"read\"] }
path \"secret/data/backup/pg-backup\" { capabilities = [\"read\"] }
HCL"
rec "vault policy write backup-read - <<'HCL'
path \"secret/data/backup/*\" { capabilities = [\"read\"] }
HCL"

rec "vault auth list | grep -q '^kubernetes/' || vault auth enable kubernetes"
rec vault write auth/kubernetes/config kubernetes_host=https://kubernetes.default.svc
rec vault write auth/kubernetes/role/textstats bound_service_account_names=textstats-secrets bound_service_account_namespaces=textstats policies=textstats-read audience=vault token_ttl=15m
rec vault write auth/kubernetes/role/backup bound_service_account_names=backup-secrets bound_service_account_namespaces=backup policies=backup-read audience=vault token_ttl=15m
rec vault read -format=json auth/kubernetes/role/textstats '|' jq -c "'.data | {bound_service_account_names, bound_service_account_namespaces, audience, policies, token_ttl}'"
