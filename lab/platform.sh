#!/usr/bin/env bash
# Installs the Lab 4 platform on the OrbStack Kubernetes cluster. Idempotent: re-running upgrades in place.
set -euo pipefail
cd "$(dirname "$0")/.."
source lab/rec.sh evidence/logs/platform.log

CERT_MANAGER=v1.21.3; CNPG=1.30.2; BARMAN_PLUGIN=v0.16.0; ARGOCD=v3.6.3; ROLLOUTS=v1.10.2

rec kubectl config current-context
rec kubectl get nodes -o wide
rec kubectl apply --server-side -f https://github.com/cert-manager/cert-manager/releases/download/$CERT_MANAGER/cert-manager.yaml '>/dev/null' '&&' echo cert-manager $CERT_MANAGER applied
rec kubectl -n cert-manager rollout status deploy/cert-manager-webhook --timeout=300s
rec kubectl apply --server-side -f https://raw.githubusercontent.com/cloudnative-pg/cloudnative-pg/release-${CNPG%.*}/releases/cnpg-$CNPG.yaml '>/dev/null' '&&' echo cloudnative-pg $CNPG applied
rec kubectl -n cnpg-system rollout status deploy/cnpg-controller-manager --timeout=300s
rec kubectl apply -f https://github.com/cloudnative-pg/plugin-barman-cloud/releases/download/$BARMAN_PLUGIN/manifest.yaml '>/dev/null' '&&' echo barman-cloud plugin $BARMAN_PLUGIN applied
rec kubectl -n cnpg-system rollout status deploy/barman-cloud --timeout=300s
rec kubectl create namespace argocd --dry-run=client -o yaml '|' kubectl apply -f -
rec kubectl -n argocd apply --server-side --force-conflicts -f https://raw.githubusercontent.com/argoproj/argo-cd/$ARGOCD/manifests/install.yaml '>/dev/null' '&&' echo argo-cd $ARGOCD applied
rec kubectl create namespace argo-rollouts --dry-run=client -o yaml '|' kubectl apply -f -
rec kubectl -n argo-rollouts apply --server-side -f https://github.com/argoproj/argo-rollouts/releases/download/$ROLLOUTS/install.yaml '>/dev/null' '&&' echo argo-rollouts $ROLLOUTS applied
rec helm upgrade --install external-secrets external-secrets/external-secrets --version 2.15.0 -n external-secrets --create-namespace --wait
rec helm upgrade --install prometheus prometheus-community/prometheus --version 30.0.1 -n monitoring --create-namespace -f deploy/platform/prometheus-values.yaml --wait
rec helm upgrade --install vault hashicorp/vault --version 0.34.1 -n vault --create-namespace -f deploy/platform/vault-values.yaml
rec kubectl -n argocd rollout status deploy/argocd-server --timeout=300s
rec kubectl -n argo-rollouts rollout status deploy/argo-rollouts --timeout=300s
rec kubectl get pods -A --sort-by=.metadata.namespace "|" grep -v "^default "
