#!/usr/bin/env bash
# Q1 part 1: object storage that holds the database's base backups and WAL archive.
set -euo pipefail
cd "$(dirname "$0")/.."
source lab/rec.sh evidence/logs/q1-dr.log

rec kubectl create namespace backup --dry-run=client -o yaml '|' kubectl apply -f -
rec kubectl apply -f deploy/backup/seaweedfs.yaml
rec kubectl -n backup wait externalsecret/seaweedfs-s3-config --for=condition=Ready --timeout=120s
rec kubectl -n backup rollout status deploy/seaweedfs --timeout=300s
rec "kubectl -n backup exec deploy/seaweedfs -- sh -c 'echo s3.bucket.create -name pg-backups | weed shell -master=localhost:9333' 2>&1 | tail -2"
rec "kubectl -n backup exec deploy/seaweedfs -- sh -c 'echo s3.bucket.list | weed shell -master=localhost:9333' 2>&1 | grep pg-backups"
