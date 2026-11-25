"""Per-question report content. Every number quoted here comes from evidence/logs."""
from build_reports import bullets, config, shot, table, term
from report_q5 import q5


def q1():
    log = "q1-dr.log"
    return "".join([
        "<h2>Design</h2>",
        "<p>The text-stats data lives in a CloudNativePG cluster <code>textstats-db</code> with two instances: "
        "a primary and a streaming replica in separate pods. Three mechanisms protect it:</p>",
        bullets(
            "<b>Backup:</b> continuous WAL archiving plus a scheduled base backup every 30 minutes, both shipped by the "
            "Barman Cloud plugin to an S3 bucket (<code>pg-backups</code>) on a separate SeaweedFS object store in the "
            "<code>backup</code> namespace. <code>archive_timeout = 60s</code> closes a WAL segment at least once a minute.",
            "<b>Failover:</b> if the primary dies, the operator promotes the replica. The app connects through the "
            "<code>textstats-db-rw</code> Service, which always points at the current primary, and opens a new connection "
            "per request, so it needs no restart.",
            "<b>Restore:</b> point-in-time recovery builds a new cluster only from the object store (base backup + WAL), "
            "replayed up to a chosen LSN. It works even if the original cluster is gone.",
        ),
        config("deploy/gitops/database.yaml"),
        "<h2>Recovery objectives</h2>",
        table(
            ["Scenario", "Objective", "Measured", "Met"],
            [
                ["Primary pod lost (failover)", "RTO &le; 30 s, RPO 0",
                 "replica promoted 4 s after the kill; writes failed for 4.79 s (108 of 7252 requests)", "Yes"],
                ["Table dropped by mistake (PITR)", "RTO &le; 10 min, RPO &le; 60 s",
                 "restore cluster healthy in 64 s, table back in the live database after 65 s; 2 rows lost", "Yes"],
                ["Whole cluster lost", "RTO &le; 10 min, RPO &le; 60 s",
                 "same path as PITR: the restore cluster is built only from the object store", "By design"],
            ],
        ),
        "<h2>Backup store and steady state</h2>",
        term(log, "seaweedfs.yaml", "wait externalsecret", "s3.bucket.create", "s3.bucket.list"),
        "<p>The bucket keys come from Vault through External Secrets (Q6). A traffic generator "
        "(<code>deploy/lab/traffic.yaml</code>) keeps writing through the app in the background during every drill, "
        "about 18 rows per second (90 rows in the 5 s after the restore).</p>",
        term(log, "traffic.yaml", "get cluster textstats-db -o wide", "pg_stat_replication", "archived_count"),
        "<h2>1. On-demand backup</h2>",
        term(log, "apply -f - <<'YAML'", "wait backup", "custom-columns", "fs.du", "fs.ls"),
        "<h2>2. Failover: the primary is killed under load</h2>",
        "<p>A probe pod sends POST /stats with 4 concurrent clients for 60 s. After 15 s the primary pod is force-deleted "
        "(no graceful shutdown), as in a node crash.</p>",
        term(log, "primary before", "killing primary", "new primary", "readyInstances", "targetPrimaryTimestamp"),
        term(log, "logs probe-failover", omit=r"^\s+\d+\s+write-ok=\d+$",
             label="probe output: seconds where every write succeeded are left out here (full output in evidence/logs/q1-dr.log)"),
        term(log, "-L role", "SELECT count(*) FROM analyses\"", pick=slice(-2, None)),
        "<h2>3. Restore: a table is dropped by mistake</h2>",
        "<p>The LSN is recorded, then the table is dropped in one transaction that also prints the last id it held. "
        "Writes fail from that moment. <code>pg_switch_wal()</code> closes the WAL segment so it reaches the object store at once.</p>",
        term(log, "pg_current_wal_lsn", "DROP TABLE", "pg_switch_wal", "after the drop", "last_archived_wal, last_archived_time FROM"),
        config("deploy/dr/restore-cluster.yaml"),
        term(log, "TARGET_LSN", "restore cluster healthy", "textstats-db-restore-1 \"SELECT"),
        "<p>The restored table matches the recorded point exactly (18829 rows, last id 18879). It is copied back into the live "
        "primary, and the app's writes succeed again without a restart.</p>",
        term(log, "pg_dump", "OWNER TO", "written_after_restore", "delete cluster textstats-db-restore"),
        "<h2>Observations</h2>",
        bullets(
            "Failover took 4 s from the kill to the new primary (CloudNativePG timestamps: target 15:32:51.36, promoted "
            "15:32:54.76). The probe saw failures only between 15.24 s and 20.03 s: 96 HTTP 503 and 12 timeouts out of 7252 "
            "writes, a 98.51% success rate over the minute. The old primary rejoined as a replica on its own.",
            "The app's readiness probe uses <code>/healthz</code>, not the database. During the failover all 10 pods "
            "stayed in the Service and returned a clean 503 on writes, instead of all leaving the Service at once.",
            "PITR lost 2 rows: the last id at the drop was 18881 and the restore stopped at 18879, because those 2 rows "
            "were committed after the LSN was taken. A full-cluster restore would lose at most the WAL not yet archived, "
            "which <code>archive_timeout = 60s</code> bounds to one minute.",
            "Restore is not instant: 64 s to rebuild the cluster from object storage for about 20 MB of backups. "
            "It grows with the database size and the amount of WAL to replay, so the RTO must be re-measured as data grows.",
            "The replica protects against losing a pod, not against mistakes: the DROP TABLE was replicated in milliseconds. "
            "Only the backups in object storage could undo it.",
            "Issues I hit: MinIO no longer publishes public images, so the object store is SeaweedFS (S3-compatible). "
            "Pulls from ghcr.io and quay.io timed out several times, and the PostgreSQL image had to be pulled by hand.",
        ),
    ])


def q2():
    log = "q2-pipeline.log"
    wf = ".github/workflows/pipeline.yml"
    return "".join([
        "<h2>Pipeline design</h2>",
        "<p>GitHub Actions runs every push to <code>main</code> and every pull request through a chain of jobs. "
        "A job starts only when the jobs it <code>needs</code> have passed, so each one is a gate:</p>",
        table(
            ["Order", "Job", "Gate"],
            [
                ["1", "secret-scan", "gitleaks over the whole git history"],
                ["1", "unit-tests", "pytest tests/unit (no database)"],
                ["2", "integration-tests", "pytest tests/integration against a real PostgreSQL 18 service container"],
                ["3", "build", "docker build, only after integration tests and secret scan passed"],
                ["4", "deploy-staging", "deploy to a throwaway kind cluster, then smoke tests against the running Service"],
                ["5", "publish", "push to GHCR, only for main and only after the staging deploy passed"],
            ],
        ),
        config(wf, "pipeline.yml - integration tests against a real database", "  integration-tests:", "  build:"),
        config(wf, "pipeline.yml - staging deploy with smoke tests, then publish", "  deploy-staging:", None),
        config("tests/smoke/test_deployed.py", "tests/smoke/test_deployed.py (runs against the deployed Service)", "def test_service"),
        "<h2>First run: every gate passed</h2>",
        term(log, "45637794856"),
        shot("q2-actions-runs", "GitHub Actions run list: green runs, the blocked run and the fix"),
        "<h2>A real bug, caught by the gate</h2>",
        "<p>The first load against the 10 new production pods returned 3 HTTP 503s. The app logs showed "
        "<code>duplicate key value violates unique constraint \"pg_class_relname_nsp_index\"</code>: several pods ran "
        "<code>CREATE TABLE IF NOT EXISTS</code> at the same moment, which PostgreSQL does not make safe. "
        "Following test-first practice, I first pushed only a regression test (commit 844c6a1) that makes 10 cold-start writes at once.</p>",
        config("tests/integration/test_database.py", "regression test", "def test_concurrent_first_writes"),
        term(log, "45645419739"),
        shot("q2-run-blocked", "Run 45645419739: integration-tests failed, so build, deploy-staging and publish never ran"),
        "<h2>The fix passes every gate</h2>",
        "<p>Commit ca2dbb8 creates the schema in its own transaction behind a PostgreSQL advisory lock, and marks it ready "
        "only after the commit. VERSION became 4.0.1.</p>",
        config("service/web.py", "service/web.py", "def ensure_schema", "def text_stats"),
        term(log, "45647118437"),
        shot("q2-run-green", "Run 45647118437: all six jobs green; image 4.0.1 published"),
        "<h2>Observations</h2>",
        bullets(
            "The broken commit produced no image: <code>build</code>, <code>deploy-staging</code> and <code>publish</code> "
            "were skipped, so nothing downstream could deploy it.",
            "Unit tests could not catch this bug. It needs a real database and concurrency, which is why the integration "
            "stage runs against PostgreSQL instead of a mock.",
            "The test failed with a second message, <code>type \"analyses\" already exists</code>, which exposed a second race: "
            "the ready flag was set before the CREATE committed. Both are fixed in the same commit.",
            "Integration and smoke tests raise an error when their database or URL is missing, instead of skipping. "
            "A gate that silently skips is not a gate.",
            "The staging database password is generated in the job and masked in the log. Publishing uses the short-lived "
            "<code>GITHUB_TOKEN</code>, so no registry password is stored anywhere.",
            "Runners are arm64 so the published image runs unchanged on the arm64 lab cluster.",
        ),
    ])


def q3():
    log = "q3-bluegreen.log"
    return "".join([
        "<h2>Design</h2>",
        "<p>Two complete copies of the app run side by side in the <code>bluegreen</code> namespace: "
        "<b>blue</b> is release 4.0.0 and <b>green</b> is release 4.0.1. Users reach the app only through the "
        "<code>text-stats</code> Service, whose selector names one colour. Switching environments is a single change "
        "to that selector, so all traffic moves at once. A second Service, <code>text-stats-preview</code>, always "
        "points at the idle colour so the new release can be tested before any user sees it.</p>",
        config("deploy/bluegreen/services.yaml"),
        config("deploy/bluegreen/green.yaml"),
        "<h2>1. Blue is live</h2>",
        term(log, "blue.yaml -f", "rollout status deploy/text-stats-blue", "curl -s http://text-stats/", pick=slice(0, 3)),
        "<h2>2. Green is deployed and tested through the preview Service</h2>",
        term(log, "green.yaml", "rollout status deploy/text-stats-green", "-L color", "text-stats-preview", "endpointslices"),
        term(log, "curl -s http://text-stats/", pick=slice(1, 2), label="what users get at this point"),
        "<p>At this point users still get blue, while green has been checked on its own endpoints.</p>",
        "<h2>3. The switch, measured</h2>",
        "<p>A probe pod inside the cluster sends <code>GET /</code> from 8 concurrent clients for 40 s and records which "
        "colour answered every request, second by second. The selector is switched after 20 s.</p>",
        term(log, "switch green; echo", "logs probe-switch", omit=r"^\s+\d+\s+(blue|green)=\d+$",
             label="probe output: seconds answered entirely by one colour are left out here (full output in evidence/logs/q3-bluegreen.log)"),
        "<h2>4. Rollback</h2>",
        "<p>Blue is still running, so going back is the same one-line change, again measured with a 30 s probe.</p>",
        term(log, "switch blue; echo", "logs probe-rollback", omit=r"^\s+\d+\s+(blue|green)=\d+$"),
        "<h2>5. Final cut-over</h2>",
        term(log, "scale deploy/text-stats-blue", "get deploy,svc", "curl -s http://text-stats/", pick=slice(-3, None)),
        "<h2>Results</h2>",
        table(
            ["Event", "Requests", "Failed", "Seconds with both colours"],
            [
                ["Switch blue to green", "13301", "0", "1 (second 20: 32 blue, 315 green)"],
                ["Rollback green to blue", "9461", "0", "1 (second 15: 223 blue, 24 green)"],
            ],
        ),
        "<h2>Advantages</h2>",
        bullets(
            "<b>Zero downtime:</b> 0 failed requests out of 22762 across a switch and a rollback.",
            "<b>Instant, atomic cut-over:</b> one selector change moved all traffic within one second. "
            "Requests already in flight finished on the old colour, which is why one second shows both.",
            "<b>Test in production before release:</b> green answered real requests through the preview Service, "
            "on the real cluster, before any user was sent to it.",
            "<b>Fast, safe rollback:</b> the previous version is still running and warm, so rolling back is not a redeploy.",
        ),
        "<h2>Limitations</h2>",
        bullets(
            "<b>Double capacity:</b> both environments run 3 pods during the release. Scaling blue to 0 afterwards "
            "saves it, but then a rollback is no longer instant.",
            "<b>All or nothing:</b> every user moves at once, so a bug that only shows under real traffic hits 100% of "
            "users until someone rolls back. Canary (Q7) limits that to a small share first.",
            "<b>Shared state:</b> these environments are stateless. With a shared database, both versions must work "
            "with the same schema, so schema changes need expand-and-contract migrations, and rolling back the app "
            "does not roll back data written by green.",
            "<b>Long-lived connections:</b> a selector change affects new connections. Clients with long keep-alive or "
            "streaming connections stay on the old colour until they reconnect.",
            "<b>Manual decision:</b> here a person runs the switch. Nothing checks green's health metrics automatically "
            "after the switch, unlike the canary analysis in Q7.",
        ),
    ])


def q4():
    log = "q4-gitops.log"
    return "".join([
        "<h2>Design</h2>",
        "<p>The directory <code>deploy/gitops</code> on the <code>main</code> branch is the single source of truth for the "
        "<code>textstats</code> namespace: the database cluster, its backups, the ExternalSecrets, the canary Rollout, its "
        "analysis template and the Service. Argo CD runs inside the cluster and <b>pulls</b> from Git. No pipeline or person "
        "runs <code>kubectl apply</code> against production, and the cluster needs no inbound access from CI.</p>",
        config("deploy/argocd/textstats.yaml"),
        table(
            ["Setting", "Effect"],
            [
                ["<code>automated</code>", "every new commit on main is applied without a manual sync"],
                ["<code>selfHeal: true</code>", "changes made directly in the cluster are reverted to what Git says"],
                ["<code>prune: true</code>", "resources removed from Git are removed from the cluster"],
                ["<code>CreateNamespace=true</code>", "the namespace itself comes from the Application, nothing is pre-created"],
                ["<code>retry</code>", "a failed sync is retried with backoff (10 s, doubling, max 3 min)"],
            ],
        ),
        "<p>Git holds only declarations. Credentials are not in the repository: the manifests contain ExternalSecrets that "
        "name a Vault path, and External Secrets fills in the values inside the cluster (Q6).</p>",
        "<h2>1. Bootstrap: the namespace is built from Git</h2>",
        "<p>The namespace does not exist. Applying the Application is the only manual step; everything else is created by Argo CD.</p>",
        term(log, "git log --oneline -1", "get namespace textstats", "deploy/argocd/textstats.yaml", "'Synced Healthy'",
             "application textstats -o wide", "cluster,objectstore"),
        term(log, "get pods -o wide", head=13),
        "<h2>2. Automated reconciliation of drift</h2>",
        "<p>Two changes are made directly in the cluster, bypassing Git: the app is scaled from 10 to 3 replicas, "
        "and the user-facing Service is deleted.</p>",
        term(log, ".spec.syncPolicy", "scale rollout", "seq 1 30", "delete service", "recreated at"),
        term(log, "argocd-application-controller --since=10m",
             label="Argo CD controller events for the two corrections"),
        "<h2>3. Releases and rollback are Git commits</h2>",
        "<p>The canary releases in Q7 were started only by commits to <code>deploy/gitops/app.yaml</code>. "
        "The faulty release (604cf45) was rolled back by reverting it in Git, not with a command against the cluster. "
        "Before the revert, the application was Synced but Degraded, because the Rollout had aborted the canary (Q7).</p>",
        term(log, "git log --oneline -4", "git show --format"),
        term(log, "kubectl -n argocd get application textstats", pick=slice(4, 5)),
        term(log, "sync.revision}')\" = 5cf9a0c", "= Healthy ]"),
        term(log, "kubectl -n argocd get application textstats", pick=slice(7, 8)),
        term(log, "rollouts get rollout"),
        "<h2>4. Sync history</h2>",
        term(log, "status.history[*]", pick=slice(-1, None)),
        term(log, "argocd-application-controller --since=20m"),
        shot("q4-argocd-tree", "Argo CD: application textstats Synced to 5cf9a0c and Healthy, with the resources it manages"),
        shot("q4-argocd-history", "Argo CD history: each deployment names its Git revision, and every one was initiated by the automated sync policy"),
        "<h2>Results</h2>",
        table(
            ["Event", "Trigger", "Result"],
            [
                ["Bootstrap", "kubectl apply of the Application", "Synced and Healthy after 774 s (mostly image pulls)"],
                ["Manual scale 10 to 3", "drift in the cluster", "spec.replicas back to 10 within 3 s (15:42:57 to 15:43:00)"],
                ["Service deleted", "drift in the cluster", "recreated 4 s later (15:43:00 to 15:43:04)"],
                ["Release 4.0.1 (604bf18)", "commit on main", "automated sync at 15:46:46, canary promoted"],
                ["Faulty release (604cf45)", "commit on main", "automated sync at 15:58:44, canary aborted, app Degraded"],
                ["Revert (5cf9a0c)", "revert commit on main", "synced at 16:03:06, Healthy at 16:03:09"],
            ],
        ),
        "<h2>Observations</h2>",
        bullets(
            "Every change in the cluster can be traced to a commit, an author and a message. The history above is also "
            "an audit log of what ran in production and when.",
            "Self-heal reacts to cluster changes within seconds, because Argo CD watches the live resources. New commits "
            "are picked up by polling Git every few minutes by default; a Git webhook would make that near-instant.",
            "Because self-heal reverts manual changes, an emergency fix made with <code>kubectl</code> is undone. "
            "Fixes must go through Git too, or the application must be paused on purpose first.",
            "The revert was the right rollback for this setup: rolling back only in the cluster would have been reverted "
            "again by Argo CD, since Git still described the faulty release.",
            "Argo CD understands Argo Rollouts health. An aborted canary shows the application as Degraded even though it "
            "is Synced, which makes the difference between \"Git was applied\" and \"the release is healthy\" visible.",
            "Bootstrap took 774 s only because image pulls from ghcr.io timed out until the PostgreSQL image was pulled by hand. "
            "The sync itself started at once.",
        ),
    ])


def q6():
    log = "q6-vault.log"
    return "".join([
        "<h2>Design</h2>",
        "<p>Every credential the deployments use lives only in HashiCorp Vault. External Secrets Operator reads it with a "
        "short-lived, namespace-bound identity and writes a Kubernetes Secret that the workloads consume. Git holds only "
        "<i>references</i> to Vault paths, never values.</p>",
        table(
            ["Credential", "Vault path", "Used by"],
            [
                ["Database login (user textstats)", "secret/textstats/db", "CloudNativePG role password and the app's DATABASE_URL"],
                ["Backup bucket keys (pg-backup)", "secret/backup/pg-backup", "Barman Cloud WAL archiving and base backups"],
                ["Object store admin keys", "secret/backup/seaweedfs-admin", "SeaweedFS S3 configuration"],
                ["Pipeline: staging DB password", "none: generated per run", "deploy-staging job, masked in the log"],
                ["Pipeline: registry login", "none: GITHUB_TOKEN", "publish job, short-lived token issued by GitHub"],
            ],
        ),
        bullets(
            "<b>Vault is not in dev mode:</b> file storage, sealed on every restart, initialised with 5 Shamir key shares and a "
            "threshold of 3, so no single key holder can unseal it. Keys and root token stay in a gitignored mode-600 file.",
            "<b>Least privilege:</b> each namespace has its own Vault role bound to one service account, a token audience of "
            "<code>vault</code>, a 15 minute TTL and a read-only policy for its own paths.",
            "<b>Audit:</b> a file audit device logs every request; secret values are HMAC-ed in the log, never stored in clear.",
        ),
        config("deploy/gitops/secrets.yaml"),
        "<h2>Vault setup</h2>",
        term(log, "vault status", "operator init", "ls -l", "check-ignore", "operator unseal", pick=slice(0, 8)),
        term(log, "audit enable", "secrets enable", "stored secret/", "kv list", "policy write", "auth enable kubernetes",
             "role/textstats bound", "role/backup bound", "read -format=json auth/kubernetes/role/textstats", omit=r"^$"),
        "<p>The first version of the roles had no audience and Vault warned about it; the roles were rewritten with "
        "<code>audience=vault</code> and the SecretStores request tokens for that audience (both runs are in the log).</p>",
        "<h2>Safe handling: nothing secret outside Vault</h2>",
        "<p>Secret values are compared only by fingerprint (first 12 hex characters of their SHA-256), so this report never "
        "shows a credential.</p>",
        term(log, "get externalsecret", "ownerReferences", "vault_fp)   kubernetes", "occurrences of the live password",
             "grep -rn password", "gitleaks"),
        "<h2>Least privilege, tested</h2>",
        "<p>Logging in exactly as External Secrets does, with the <code>textstats-secrets</code> service account token:</p>",
        term(log, "create token textstats-secrets"),
        "<h2>Audit trail</h2>",
        term(log, "cat /vault/audit/audit.log"),
        "<p>Each entry names the identity, the path and the outcome. The two denied requests above are recorded with their "
        "error, and passwords appear only as <code>hmac-sha256:...</code>.</p>",
        "<h2>Rotation under live traffic</h2>",
        "<p>A probe writes through the app with 4 concurrent clients for 180 s. The password is replaced in Vault after "
        "about 11 s; External Secrets is told to refresh at once (it would also pick it up within its 1 minute interval); "
        "CloudNativePG changes the role's password when the Secret changes; then the app pods are restarted so they read "
        "the new connection string.</p>",
        term(log, "username=textstats password=$(openssl rand -hex 20) | grep", "force-sync", "until [ \"$(k8s_fp)",
             "kubectl argo rollouts restart", "logs probe-rotation", "P=$(kubectl -n textstats get cluster", "metadata get secret/textstats/db | grep -E '^(current_version"),
        term(log, "error_severity", "baseline after the rotation", pick=slice(-2, None)),
        "<h2>Results</h2>",
        table(
            ["Check", "Result"],
            [
                ["Live password in any git commit", "0 occurrences; gitleaks: no leaks found"],
                ["Vault value vs Kubernetes Secret", "same fingerprint (a27b6eef93c8 before, 6052e151bf5b after rotation)"],
                ["Read another namespace's secret", "403 permission denied (and logged)"],
                ["Write own secret", "403 permission denied (read-only policy)"],
                ["Vault to Kubernetes Secret after rotation", "under 1 s (16:06:54 both)"],
                ["All 10 app pods on the new secret", "16:07:07, 13 s after the rotation"],
                ["Database login errors", "16:06:55 to 16:07:02 (8 s), pods still holding the old password"],
                ["Writes during the 180 s probe", "19562 of 19775 succeeded (98.92%); 180 of the 213 failures fell in seconds 11-21"],
                ["Old password after rotation", "password authentication failed"],
            ],
        ),
        "<h2>Observations</h2>",
        bullets(
            "The rotation is not free: between CloudNativePG changing the role and the last pod restarting, pods with the old "
            "password returned 503 on writes. Ways to avoid it: two database users rotated alternately, or Vault's database "
            "secrets engine issuing short-lived per-pod credentials.",
            "The remaining 33 failures were isolated timeouts after every pod had been replaced, while a browser and "
            "Prometheus queries for the screenshots were running on the same laptop. A 60 s baseline straight afterwards "
            "had 0 failures in 7646 writes.",
            "Restarting the app is still a manual step here. A reloader that restarts pods when their Secret changes would "
            "close that gap.",
            "An earlier rotation at 16:04 (version 2, visible in the PostgreSQL log) was repeated because my script's wait "
            "returned before the pods were really replaced; the recorded run uses a check on pod creation times.",
            "Vault itself becomes critical: after a restart it is sealed until 3 key holders unseal it. Existing Kubernetes "
            "Secrets keep working meanwhile, but no new secret or rotation can be read. Production would use auto-unseal with a KMS.",
            "The pipeline holds no long-lived secrets at all: the staging password is generated and masked per run and "
            "publishing uses the short-lived <code>GITHUB_TOKEN</code>.",
        ),
    ])


def q7():
    log = "q7-canary.log"
    good, bad = slice(0, 1), slice(1, 2)
    steps = r"^\s+(\[ \"\$s\"|case |sleep 2; done|s=\$\(kubectl)"
    return "".join([
        "<h2>Design</h2>",
        "<p>The app is an Argo Rollouts <code>Rollout</code> with 10 pods behind one Service. A new version starts on "
        "1 pod (10% of traffic), then 3 pods (30%) and 6 pods (60%), and must pass an analysis after each step before "
        "it gets more traffic. There is no service mesh, so the traffic split comes from the pod count: the Service "
        "selects every pod, and each pod gets an equal share of requests.</p>",
        config("deploy/gitops/app.yaml", "deploy/gitops/app.yaml (strategy)", "  strategy:", "---"),
        "<p>The analysis queries Prometheus for the canary's own pods only. Prometheus copies the pod label "
        "<code>rollouts_pod_template_hash</code> onto every series, and Argo Rollouts passes in the hash of the new revision.</p>",
        config("deploy/gitops/app.yaml", "deploy/gitops/app.yaml (AnalysisTemplate)", "kind: AnalysisTemplate", "# User-facing Service"),
        table(
            ["Rollback trigger", "Threshold", "Measured", "On failure"],
            [
                ["5xx share of /stats on canary pods, last 1 min", "must be &le; 2%", "every 20 s, 3 times per analysis",
                 "more than 1 failed measurement (failureLimit 1) aborts the rollout"],
                ["p95 latency of /stats on canary pods, last 1 min", "must be &lt; 250 ms", "every 20 s, 3 times per analysis",
                 "same"],
            ],
        ),
        "<p>On abort, Argo Rollouts scales the canary to zero and the stable version gets all pods back, without a person and "
        "without a new deploy. A steady traffic generator (<code>deploy/lab/traffic.yaml</code>) provides the requests the analysis measures.</p>",
        "<h2>Run 1: release 4.0.1 (healthy)</h2>",
        "<p>Started by commit 604bf18 (Q4). The pause steps hold each weight for 30 s, and each analysis takes 3 measurements 20 s apart.</p>",
        term(log, "git log -1", pick=good),
        term(log, "sync.revision}')\" = 604bf18"),
        term(log, "last=\"\"; while", pick=good, omit=steps,
             label="rollout timeline (the loop prints a line whenever the step or phase changes; this run's format had no pod-count field)"),
        table(
            ["Step", "Action", "Reached at"],
            [
                ["1", "10% (1 of 10 pods), pause 30 s", "15:46:51"],
                ["2", "analysis 1", "15:47:20"],
                ["3-4", "30% (3 pods), pause 30 s", "15:47:59"],
                ["5", "analysis 2", "15:48:30"],
                ["6-7", "60% (6 pods), pause 30 s", "15:49:11"],
                ["8", "analysis 3", "15:49:42"],
                ["9-10", "100%, Healthy", "15:50:21 / 15:50:25"],
            ],
        ),
        term(log, "analysisrun --sort-by=.metadata.creationTimestamp -o json", pick=good),
        term(log, "requests/s per pod-template hash", pick=good),
        shot("q7-good-dashboard", "Argo Rollouts dashboard after run 1: all steps done, revision 2 (4.0.1) stable on 10 pods, 3 analysis runs passed"),
        "<h2>Run 2: a defective release</h2>",
        "<p>Commit 604cf45 turns on <code>FAULT_RATE=0.3</code>, so 30% of <code>/stats</code> requests on the new pods fail. "
        "It stands in for a bug that the tests did not catch.</p>",
        term(log, "git log -1", pick=bad),
        term(log, "git show --stat", pick=bad),
        term(log, "sync.revision}')\" = 604cf45"),
        term(log, "last=\"\"; while", pick=bad, omit=steps),
        shot("q7-bad-canary-10", "During run 2: the canary (revision 3) on 1 of 10 pods, analysis 3-2 running"),
        term(log, "rollouts get rollout text-stats", pick=bad, omit=r"(├|│)\s+(│\s+)?(├|└)──□"),
        term(log, "analysisrun --sort-by=.metadata.creationTimestamp -o json", pick=bad),
        term(log, "requests/s per pod-template hash", "5xx share per pod-template hash", pick=slice(2, 4)),
        term(log, "kubectl -n argocd get application textstats", pick=bad),
        shot("q7-bad-dashboard", "After the abort: revision 3 has no pods, its analysis failed, revision 2 stays stable"),
        "<h2>Rollout metrics</h2>",
        shot("q7-prometheus-requests", "Requests/s per pod-template hash. Run 1 (15:46-15:51): traffic moves step by step from "
             "847b8dd87b (4.0.0) to 5488d754bf (4.0.1). Run 2 (about 15:59-16:00): the canary 65d8f59779 takes about 1 req/s, then drops to 0"),
        shot("q7-prometheus-error-rate", "5xx share per pod-template hash. Only the faulty canary 65d8f59779 has errors, between about "
             "0.24 and 0.32, while the stable pods stay at 0"),
        table(
            ["", "Run 1 (4.0.1)", "Run 2 (fault injection)"],
            [
                ["Error-rate measurements", "0, 0, 0 in each of 3 analyses", "0.271, 0.266 (limit 0.02)"],
                ["p95 latency measurements", "0.024-0.039 s", "0.024 s (passed; latency was not the problem)"],
                ["Analysis runs", "3 successful", "1 failed"],
                ["Most pods on the new version", "10 of 10", "1 of 10"],
                ["Time from sync to the end", "15:46:46 to 15:50:25, Healthy", "15:58:46 to 15:59:40, aborted"],
                ["Time from analysis start to abort", "-", "21 s (15:59:19 to 15:59:40)"],
                ["Canary request rate at the end", "-", "1.23 req/s vs 14.91 req/s on stable"],
            ],
        ),
        "<h2>Observations</h2>",
        bullets(
            "The rollback trigger worked as designed: the second error-rate measurement above 2% exceeded the failure limit, "
            "and the rollout aborted with no human action. Only 1 of 10 pods ever ran the faulty version.",
            "Watching only latency would have missed this bug: p95 stayed at about 24 ms because failing requests return quickly. "
            "Both metrics are needed.",
            "Weights come from pod counts, so they move in 10% steps and need 10 replicas. Exact or very small weights "
            "(for example 1%) would need traffic routing in a service mesh or ingress controller.",
            "There is no stickiness: a user can hit the canary on one request and the stable version on the next. "
            "The canary is a share of requests, not a fixed subset of users; header- or cookie-based routing needs a traffic router.",
            "The analysis is only as good as its traffic. The canary got about 1.2 requests/s, so each one-minute window held "
            "roughly 70 requests. A rare error (well below 2%) could pass, so longer windows or more traffic are needed for subtle faults.",
            "Both versions share one database during the rollout, so a release that changes the schema must stay compatible "
            "with the version still running on the other pods.",
            "After the abort, Git still described the faulty release, and Argo CD showed the app Degraded. The release was "
            "finished by reverting the commit (Q4), so Git and the cluster agree again.",
        ),
    ])


REPORTS = {
    1: ("q1-disaster-recovery", "Disaster recovery",
        "Design and demonstrate a disaster recovery mechanism (backup, restore, failover) and document recovery "
        "objectives and observations.", q1),
    2: ("q2-cicd-test-gates", "Automated testing in a CI/CD pipeline",
        "Implement automated testing within a CI/CD pipeline, integrating unit/integration tests as pipeline gates "
        "before deployment.", q2),
    3: ("q3-blue-green", "Blue-Green deployment",
        "Implement a Blue-Green deployment strategy and demonstrate zero-downtime switching between environments. "
        "Analyze the advantages and limitations.", q3),
    4: ("q4-gitops", "GitOps-based delivery",
        "Implement GitOps-based delivery where the Git repository is the single source of truth for declarative "
        "deployments, and demonstrate automated reconciliation.", q4),
    5: ("q5-advanced-deployment-report", "Advanced deployment strategies report",
        "Prepare an advanced deployment strategies report comparing blue-green, canary, GitOps, secret management, "
        "and disaster recovery approaches with risk analysis, evidence, and conclusions.", q5),
    6: ("q6-secret-management", "Secret management",
        "Implement secret management for the pipeline and deployments using a secure vault/secret store, and "
        "demonstrate safe handling of credentials.", q6),
    7: ("q7-canary", "Canary deployment",
        "Implement a Canary deployment strategy, gradually roll out a new version to a subset of users, and analyze "
        "rollout metrics and rollback triggers.", q7),
}
