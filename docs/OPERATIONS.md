# Operations runbook

Production SLOs and worker counts in the implementation plan are acceptance targets. This
scaffolding has not met them through live fault injection or a sustained production run.
An HTTP 200 from `/healthz`, passing Python tests, a running container, or a model response does
not establish verified science, healthy dependencies, or safe capacity.

## Release and migration

Record the reviewed source commit, `uv.lock` digest, console lock digest, application-image
SHA-256, Terraform/provider locks, database revision, exact experiment model configurations,
reviewed price sources, VM template IDs and verifier qualification inputs for every release.
An unrecorded `latest` image or silent model change is not a release.

Alembic is the deployed schema authority; production disables `auto_create_schema`. The initial
revision is a frozen snapshot, including canonical records, commands, events, outbox, budgets,
reservations, leases, dependency edges and token ledger columns. It has server defaults for
counters and nonnegative ledger/revision checks. Future changes require new immutable revisions;
never import changing application `Base` metadata into historical migrations.

Before a release, test the upgrade on a restored database copy and test the previous application
against the expanded schema. Review constraints for legacy rows before adding them. Run exactly
one authorized migration task using the schema-owner role, check its actual exit code, then roll
out application tasks with circuit-breaker rollback enabled. API and worker identities must not
have migration authority. Preserve a database backup and the previous image before rollout.

Use expand/contract migrations when old and new tasks overlap. Do not automatically downgrade
production on application failure: the initial downgrade drops canonical tables. Roll back the
application image where compatible, or restore a separate database and reconcile as an incident.
Existing development databases created by `create_all` must be compared with the frozen schema;
do not stamp them as migrated without verifying columns, indexes, defaults, constraints and data.

## Secrets and permissions

Provider credentials belong on trusted research workers; E2B/model-generated programs receive
neither canonical database credentials nor receipt/verification authority. API, worker and
migration task roles are separate. ECS execution roles fetch only the configured secret ARNs;
application task roles do not receive generic Secrets Manager read access. Custom secret KMS key
ARNs must be explicitly supplied when necessary.

For rotation, create a new secret version, deploy new tasks, confirm successful authenticated
operation, drain prior tasks, then retire old authority. Rotate database role passwords with a
coordinated compatibility window or replacement role. Preserve audit evidence. Do not expose
secrets in command-line arguments, Terraform data sources/state, logs, trace payloads or exports.
RDS's generated administrative secret is for secure bootstrap/recovery only, not API injection.

Monitor the pinned RDS root-CA bundle and provider/SDK advisories. Update public trust-store
bytes and their recorded digest together, test TLS identity validation, and release a new image.

## Monitoring and admission

Inspect correlated errors, transactional outbox state/age, lease ages and fencing conflicts,
uncertain provider operations, budget reservations/spend, token totals, queue latency, worker
heartbeats, API latency, artifact read/write failures, RDS connections/replication and Temporal
service/namespace health. Unconfigured services should remain `unavailable` or `unqualified`.
Do not convert configuration presence into a green health claim.

Worker count is a deployment control, not an experiment's spending authority. Every experiment
still has its own allocation/price/concurrency limits. Stop admission when budget reconciliation,
provider usage, required exact-model pricing, template qualification or dependency health is
uncertain. Do not replace a failed requested model with an available model. Set worker desired
count back to zero to stop new polling during a controlled maintenance window; first pause
experiments and allow active work to checkpoint or explicitly reconcile interruptions.

For a compromised credential or uncontrolled allocation, revoke the narrow affected provider
credential/role, stop worker allocation and preserve records. Terminating a local HTTP coroutine
or ECS task does not prove an external model/VM operation stopped or stopped billing. Reconcile
provider IDs and actual usage before releasing uncertain reservations.

## Backups and disaster recovery

RDS is configured for 35-day automated backup retention and Multi-AZ operation; canonical S3
artifacts have versioning and deletion protection at the infrastructure layer. Those settings
alone do not prove the target RPO <=5 minutes or RTO <=1 hour. Cross-region replication, explicit
backup vault policies and restore drills remain deployment-specific work. Keep Terraform state
in a separate encrypted/versioned restricted bucket and retain the KMS keys needed for recovery.

A restore drill must reconstruct both canonical metadata and referenced artifact bytes:

1. Restore RDS to a separate instance at the selected point in time, with new scoped credentials.
2. Verify the Alembic revision, project boundaries, event/outbox continuity and accepted-receipt
   records before allowing write traffic. Do not start old workers against the restored database.
3. Retrieve every referenced accepted artifact and dependency by its recorded digest. Use S3
   versions to recover missing/overwritten objects; never silently substitute a similar proof.
4. Compare recovered provider/Temporal operations with authoritative external status. Mark
   ambiguous model calls, child allocations and VM requests uncertain; do not blindly replay
   them as though no work occurred. Reissue only after idempotency and ownership are established.
5. Rebuild public proof packages from reviewed targets, accepted dependency closures, pinned
   tools and qualified kernels. Caches and snapshots are replaceable; acceptance evidence is not.
6. Record measured loss window, restore time, recovered counts, unresolved operations and failures.
   Keep admission paused until an operator accepts the reconstructed authority state.

Development volumes are persistent convenience, not managed backups. `docker-compose down`
retains named volumes; `down -v` destroys them. Never recommend volume deletion as a migration or
recovery procedure. A local PostgreSQL dump and local artifact copy can aid development recovery,
but cross-store consistency must be checked before treating them as a reproducibility package.

## Fault-injection and scale qualification

Before wave 3 qualification, inject failures around provider dispatch/response, usage commit,
artifact upload, receipt commit, outbox delivery, lease expiry, worker restart and database failover.
Demonstrate that accepted artifacts remain retrievable, fencing rejects stale workers, budgets
do not admit uncontrolled descendants, and ambiguous external operations remain visible.

The 128-active-worker/72-hour qualification must distinguish model work, verification,
simulation and idle tasks; measure real accepted outcomes, cost, useful reuse, recovery,
cancellation latency, API p95 and console update latency. Do not count fake SDK calls, idle
containers or mocked model events as active research. The 1,000-worker qualification requires
its own live run and recovery evidence. Record failure modes instead of rounding them into success.

## Independent proof acceptance

The qualified Linux acceptance boundary is distinct from the API/research deployment. Run
candidate source only through that boundary with immutable trusted targets, pinned environment
and operator qualification evidence. A successful compiler process is not acceptance. A model
cannot populate its own expert review or approved axiom policy. Publication requires the
configured independent-kernel tier; unavailable kernels produce blocked status.

Use the manually gated qualified-verifier CI only on trusted revisions and a separately
administered Linux runner. Review its real result artifact and exact qualification pins. Do not
change `formal/qualification.json` from blocked/unqualified solely because workflow files exist
or generic CI passes.
