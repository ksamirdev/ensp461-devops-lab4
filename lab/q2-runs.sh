#!/usr/bin/env bash
# Q2: record what a pipeline run did, job by job: lab/q2-runs.sh <run-id> [failed-job-log]
set -euo pipefail
cd "$(dirname "$0")/.."
source lab/rec.sh evidence/logs/q2-pipeline.log
rec gh run view "$1" --repo ksamirdev/ensp461-devops-lab4
if [ "${2:-}" = failed-job-log ]; then
  rec "gh run view $1 --repo ksamirdev/ensp461-devops-lab4 --log-failed | grep -E 'PASSED|FAILED|Error|assert|passed|failed' | awk -F'\t' '{print \$NF}' | sed -E 's/^[0-9T:.-]+Z //' | head -30"
fi
