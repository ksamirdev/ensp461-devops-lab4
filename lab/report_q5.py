"""Q5: advanced deployment strategies report. Every number quoted here comes from evidence/logs."""
from build_reports import bullets, shot, table


def q5():
    return "".join([
        "<h2>1. Scope and environment</h2>",
        "<p>One application, the text-stats service (Flask + PostgreSQL), was taken through every approach in this lab on "
        "the same cluster, so the results can be compared directly. Kubernetes v1.36 runs single-node in OrbStack (arm64, "
        "8 GB, 6 CPUs) on macOS. The pipeline runs on GitHub Actions arm64 runners and publishes to GHCR.</p>",
        table(
            ["Concern", "Tool (pinned version)", "Question"],
            [
                ["CI and test gates", "GitHub Actions, pytest, kind, gitleaks v8.30.1", "Q2"],
                ["Release by traffic switch", "Kubernetes Service selector", "Q3"],
                ["Declarative delivery", "Argo CD v3.6.3", "Q4"],
                ["Progressive release", "Argo Rollouts v1.10.2, Prometheus (chart 30.0.1)", "Q7"],
                ["Secrets", "Vault (chart 0.34.1), External Secrets 2.15.0", "Q6"],
                ["Database, backup, failover", "CloudNativePG 1.30.2, Barman Cloud plugin v0.16.0, SeaweedFS S3", "Q1"],
            ],
        ),

        "<h2>2. Comparison of the approaches</h2>",
        table(
            ["Approach", "Protects against", "Mechanism here", "Measured evidence", "Cost / complexity", "Main risk"],
            [
                ["Blue-green", "Downtime during a release; slow rollback",
                 "Two full Deployments; one Service selector switch",
                 "0 failed of 13301 requests across the switch, 0 of 9461 across the rollback",
                 "Low tooling; double capacity during a release",
                 "A bad version reaches 100% of users at once"],
                ["Canary", "A bad release reaching every user",
                 "Argo Rollouts 10/30/60/100% steps with Prometheus analysis",
                 "Good release: 3 analyses passed, error rate 0. Bad release: error rate 0.27 vs 0.02 limit, aborted with 1 of 10 pods on it",
                 "Medium: metrics, analysis templates, enough traffic to measure",
                 "Bad metrics or thresholds pass a bad build, or block a good one"],
                ["GitOps", "Configuration drift; untracked manual changes; unclear history",
                 "Argo CD auto-sync with prune and self-heal from deploy/gitops on main",
                 "Manual scale undone in about 3 s, deleted Service back in 4 s, Git revert synced and Healthy 3 s later",
                 "Medium: one controller; every change becomes a commit",
                 "Whoever can push to main can change production"],
                ["Secret management", "Leaked or long-lived credentials; secrets in Git",
                 "Vault KV v2 + Kubernetes auth; External Secrets syncs into Secrets",
                 "gitleaks secret-scan job passes on every pipeline run; per-namespace least-privilege policies; rotation reached Kubernetes in under 1 s and all 10 pods in 13 s, with 213 of 19775 writes failing during the switch",
                 "Medium-high: Vault must be unsealed and kept available",
                 "Vault sealed or down blocks new syncs; rotation can break running pods"],
                ["Disaster recovery", "Pod or node loss; operator mistakes; data loss",
                 "Streaming replica with automatic failover; WAL archive + base backups to S3; PITR",
                 "Failover: new primary in 4 s, writes failed for 4.79 s (108 of 7252). PITR: 64 s, 2 rows lost",
                 "Medium: object store, backup schedule, restore drills",
                 "Untested backups; RTO grows with data size"],
            ],
        ),

        "<h2>3. Risk analysis</h2>",
        table(
            ["Risk", "Likelihood", "Impact", "Mitigation in this lab", "Residual risk"],
            [
                ["Bad release reaches all users", "Medium", "High",
                 "Test gates (Q2), canary analysis stops at 10% (Q7), blue-green instant rollback (Q3)",
                 "Bugs that do not show in error rate or latency (wrong results) still pass the canary"],
                ["Schema incompatible between old and new version", "Medium", "High",
                 "Schema created idempotently under an advisory lock; additive changes only",
                 "No migration tooling; destructive changes need expand-and-contract by hand"],
                ["Configuration drift", "High", "Medium",
                 "Argo CD self-heal and prune revert manual changes within seconds (Q4)",
                 "Resources outside deploy/gitops (lab tooling, restore clusters) are not watched"],
                ["Leaked credential", "Medium", "High",
                 "Values only in Vault; gitleaks on every pipeline run; least-privilege policies; audit log",
                 "A Kubernetes Secret is still readable by anyone with get secret in the namespace"],
                ["Outage during credential rotation", "Medium", "Medium",
                 "Vault, External Secrets and CNPG managed role change together; pods restarted in a rolling way",
                 "Pods still holding the old password fail until they restart: 8 s of password errors, 213 of 19775 writes failed (98.92% success)"],
                ["Data loss by operator error", "Medium", "High",
                 "WAL archiving with archive_timeout 60 s; PITR to a chosen LSN (Q1)",
                 "Writes after the recovery target are lost (2 rows in the drill)"],
                ["Primary database node failure", "Medium", "High",
                 "Streaming replica, automatic promotion, -rw Service follows the primary",
                 "Seconds of failed writes (4.79 s measured); single-node lab cluster is itself a single point of failure"],
                ["Backup store loss", "Low", "High",
                 "Backups on a separate S3 store with its own credentials",
                 "Store runs on the same physical node here; production needs off-site replication"],
                ["Pipeline bypass (direct push of an image)", "Low", "High",
                 "Only images built and tested by the pipeline are published; Argo CD deploys only what Git names",
                 "No admission policy or image signing enforces it inside the cluster"],
                ["Vault sealed or unavailable after a restart", "Medium", "Medium",
                 "Existing Kubernetes Secrets keep working; unseal needs 3 of 5 key holders",
                 "New secrets and rotations stop until someone unseals; auto-unseal (KMS) would remove this"],
                ["Argo CD or Git unavailable", "Low", "Medium",
                 "The cluster keeps running its last synced state; nothing is deleted",
                 "No new deployments or drift correction until it is back"],
            ],
        ),

        "<h2>4. Evidence summary</h2>",
        bullets(
            "<b>Q1 Disaster recovery:</b> primary force-deleted under load; replica promoted 4 s later (15:32:50 to 15:32:54); "
            "writes failed for 4.79 s, 108 of 7252 requests (98.51% success). A dropped table was rebuilt by point-in-time "
            "recovery from object storage: restore cluster healthy after 64 s, table back in the live database after 65 s, "
            "2 rows lost (last id 18881 at the drop, 18879 restored).",
            "<b>Q2 CI/CD gates:</b> run 45645419739 with a failing regression test stopped at integration-tests; build, "
            "deploy-staging and publish were skipped, so no image existed for the broken commit. The fix (run 45647118437) "
            "passed all six jobs and published 4.0.1.",
            "<b>Q3 Blue-green:</b> 0 failed requests out of 13301 during the switch and 0 out of 9461 during the rollback; "
            "each switch took effect within one second.",
            "<b>Q4 GitOps:</b> the namespace was built from Git with no manual apply. A manual scale to 3 was back at 10 "
            "replicas 3 s later, a deleted Service was recreated after 4 s, and a Git revert was synced at 16:03:06 and "
            "Healthy at 16:03:09.",
            "<b>Q6 Secrets:</b> Vault initialised with 5 key shares and threshold 3; unseal keys never printed or committed; "
            "each namespace reads only its own paths; a rotation reached the cluster in under 1 s; 213 of 19775 writes failed while pods still held the old password, and the old password was then rejected.",
            "<b>Q7 Canary:</b> 4.0.1 passed three analyses (error rate 0, p95 about 24-39 ms) and reached 100% at 15:50:25. "
            "The faulty build measured error rates of 0.271 and 0.266 against a 0.02 limit and was aborted at 15:59:40, "
            "21 s after its first analysis started, having run on 1 of 10 pods.",
        ),
        shot("q7-bad-dashboard", "Q7: the defective canary aborted; revision 3 scaled to zero, stable revision 2 keeps all 10 pods"),

        "<h2>5. When to use which, and how they combine</h2>",
        bullets(
            "<b>Blue-green</b> when you need an instant, whole-system switch and rollback, the app is stateless or "
            "schema-compatible, and you can afford double capacity for a short time.",
            "<b>Canary</b> when real traffic is the best test, metrics can tell good from bad, and limiting the blast radius "
            "matters more than release speed (here about 3.5 minutes per release).",
            "<b>GitOps</b> for every environment that should be reproducible and auditable: it delivers both strategies above "
            "and makes rollback a <code>git revert</code>.",
            "<b>Secret management</b> always: it is a prerequisite, not an alternative. Every other approach here handles "
            "credentials, and none of them should see a password in Git.",
            "<b>Disaster recovery</b> always for stateful services: release strategies protect against bad code, only backups "
            "and replicas protect against lost data and lost nodes.",
        ),
        "<p>In this lab they work as one chain: the <b>CI pipeline</b> lets only tested images exist; a commit to "
        "<code>deploy/gitops</code> is the only way to change production, and <b>Argo CD</b> applies it; <b>Argo Rollouts</b> "
        "releases it as a <b>canary</b> and stops it on bad metrics; <b>Vault</b> supplies every credential through External "
        "Secrets; and <b>CloudNativePG</b> keeps the data recoverable whatever happens to a pod or a table.</p>",

        "<h2>6. Conclusions</h2>",
        bullets(
            "No single strategy is enough. Each one closed a different failure in the drills: the test gate stopped a "
            "concurrency bug, the canary stopped a fault the tests could not see, self-heal undid manual drift, and PITR "
            "recovered a dropped table that the replica had already copied.",
            "Canary gave the smallest blast radius (1 of 10 pods) and a fully automatic rollback, at the cost of slower "
            "releases and a dependency on good metrics. Blue-green gave the fastest, simplest switch with zero failed "
            "requests, but exposes all users at once.",
            "GitOps turned every production change, including rollbacks, into a commit with a recorded sync, which "
            "is the audit trail the other approaches rely on.",
            "Recovery objectives must be measured, not assumed: failover cost 4.79 s of failed writes and PITR 65 s and 2 "
            "rows. Both numbers will grow with data size and must be re-tested regularly.",
            "The main remaining gaps are outside this single-node lab: off-site backup replication, Vault auto-unseal, "
            "image signing with admission control, and multi-node failure domains.",
        ),
    ])
