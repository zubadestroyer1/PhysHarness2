# Infrastructure implementation report

Owned paths only: `infra/`, `migrations/`, `alembic.ini`, `Dockerfile`, `compose.yaml`,
`.dockerignore`, `.github/`, `docs/OPERATIONS.md`, `docs/DEPLOYMENT.md`,
`tests/test_infrastructure.py`, and this report. No commits, cloud plans, applies, paid calls,
image pushes or running containers were performed.

## Delivered

### Frozen database migration

- `alembic.ini` requires an explicit environment/config database URL; no hidden default DB.
- `migrations/env.py` does not import runtime models. Supports online/offline migration and an
  externally supplied transaction connection (used by the isolated PostgreSQL integration test).
- `migrations/versions/0001_canonical_store.py` freezes the current eight tables: `records`,
  `commands`, `events`, `outbox`, `budgets`, `reservations`, `leases`, `dependencies`.
- Includes parent's token fields: budgets `max_tokens`, `tokens_reserved`, `tokens_spent`;
  reservations `tokens_reserved`, `tokens_actual`.
- All runtime-model indexes and nullability match. Counter defaults are server-side as well as
  application-side. Check constraints reject negative costs/counters/tokens and invalid revision
  or concurrency values. Consumption is allowed to exceed a cap for honest overage reconciliation;
  no SQL constraint prevents recording actual provider costs.
- Upgrade, downgrade, upgrade again, schema comparison and PostgreSQL offline DDL pass. Historical
  revision imports no `Base`; future schema changes require a new revision.

### Images, local Compose and Dockerfile

- `infra/images.lock.json` records registry-resolved SHA-256 manifests, explicitly labeled
  `manifest_metadata_only`: Python 3.12.13, uv 0.11.14, Postgres 16, Temporal Server/Admin 1.31.0,
  Temporal UI 2.49.1. No latest tags or unrecorded default image fallback.
- `Dockerfile` builds a Python3.12 image from mandatory digest inputs and frozen `uv.lock`, installs
  E2B/science extras, carries migrations, runs as UID10001 and exposes a writable scratch volume.
  API entry: `python -m uvicorn physharness.api:create_app --factory --host 0.0.0.0 --port 8000`.
- Worker override: `python -m physharness.worker`; migration override:
  `python -m alembic upgrade head`.
- `.dockerignore` excludes source-control metadata, local state/secrets, tools, console build
  context and credentials. Its only PEM exception is the public pinned RDS CA bundle.
- Compose uses durable PostgreSQL, supported Temporal server/admin-tools images, separate schema
  and namespace jobs, optional API/migrate profile, explicitly separate worker profile, persistent
  local artifacts and loopback-only host ports. Worker depends on migration completion.
- `infra/prepare_local.py` exclusively creates a new mode0600 `.env`, with random role-scoped
  researcher/reviewer/operator credentials, random DB password and locked image inputs. No model
  keys and an empty model-price table. It refuses overwrite and never prints credentials.
- Real standalone Docker Compose 5.5.0 validated all profiles using a temporary private env file.
  `docker compose` plugin is unavailable here, but `/opt/homebrew/bin/docker-compose` works.
- The Docker daemon is absent (`/var/run/docker.sock` not found). No image build/startup or live
  Temporal schema bootstrap is claimed as tested. Container build/import and PostgreSQL tests
  are defined in CI for a real Linux runner.

### Managed AWS Terraform

`infra/terraform/aws` contains:

- Explicit region/AZ, image digest, certificate/private CIDRs, RDS minor version, bucket name,
  existing secret ARN, Temporal namespace/endpoint, CORS and exact-model-price inputs.
- VPC, two AZs, public NAT subnets, private application subnets, isolated RDS subnets, private
  Fargate tasks, internal TLS ALB, PostgreSQL-only DB ingress, HTTPS/Temporal provider egress,
  S3 gateway endpoint. No task/DB public IP and no unrestricted ALB ingress default.
- Private encrypted Multi-AZ RDS PostgreSQL 16, server-required TLS, managed administrative secret,
  35-day backups, fixed minor-version input, explicit retirement snapshot, deletion protection.
- Versioned private KMS artifact bucket, public-access blocking, TLS policy, prevent-destroy;
  app roles can Get/Put/List but cannot delete objects.
- Separate API, worker, migration execution and task IAM roles. Secrets Manager access is scoped
  to each task's configured secret ARNs. No raw secret values are read into Terraform state.
- API receives canonical DB/auth secrets. Worker also receives OpenAI/Temporal credentials and
  optional E2B credentials/template. Migration receives only its separate schema-owner DB secret.
- Exact model selection comes from experiment records, not worker defaults. Worker environment
  sets `PHYSHARNESS_MODEL_PRICES` (the supplied reviewed exact-model table), standard provider keys,
  `PHYSHARNESS_TEMPORAL_TLS=true`, address/namespace/API key, optional E2B template.
- Separate one-shot migration definition, service rollback circuit breakers, CloudWatch logs,
  init processes, read-only container roots and writable scratch volume. Both service desired
  counts default 0 so bootstrap does not begin research allocation.
- Public RDS CA bundle pinned at SHA-256
  `e5bb2084ccf45087bda1c9bffdea0eb15ee67f0b91646106e466714f9de3c7e3`; image provides
  `/app/rds-ca.pem`, tasks set `PGSSLROOTCERT` and `PGSSLMODE=verify-full`.
- Existing managed Temporal service, VPN/network attachment, DNS/certificate, registry, secret
  values, console hosting and qualified proof-acceptance workers are explicit external inputs or
  separate deployment work. Plain Fargate does not provide a Docker/Landlock proof boundary.
- `terraform.tfvars.example` and `backend.hcl.example` intentionally contain replacement markers.
  Actual service inputs need reviewed values; no unsafe automatic defaults substitute them.

Terraform binary was not installed initially. Downloaded official Terraform 1.16.2 into
`/tmp/physharness-infra-tools/terraform`, verified archive SHA-256
`7c0a0b31c8aa541351369bcf7b62a7289fbc21de7e577669aeba6d42f4e6cc41` against HashiCorp checksums.
Initialized only with `-backend=false`; installed signed AWS provider 6.10.0 and recorded
Linux amd64/macOS arm64 checksums in `.terraform.lock.hcl`. `fmt -check` and actual provider-backed
`validate` pass. The local sandbox blocked provider plugin IPC, so validation ran with reviewed
sandbox escalation. No AWS plan/apply, credentials or state backend was involved.

### CI and qualification boundaries

- `.github/workflows/ci.yaml`: read-only default permissions; pinned external action commits;
  exact Python/uv/Node versions; locked Python dependencies; project lint/unit tests; metadata
  validation; console test/build; Terraform init without backend/readonly lock + validate;
  actual image build/import test without publishing; dedicated real PostgreSQL migration test.
- PostgreSQL CI is disposable and tests a unique schema, never drops a shared database. Local
  live-Postgres test skips only when no `PHYSHARNESS_TEST_DATABASE_URL` is configured.
- `.github/workflows/qualified-lean.yaml`: manual, protected environment, labeled self-hosted
  Linux runner; requires operator-owned bundle/qualification/case inputs with exact digests.
- `infra/run_qualified_lean.py` uses the actual `ComparatorVerifier`, not subprocess Lean on the
  API host or fake protocol responses. Cases include operator-provided semantic review; no review
  is manufactured. Requires both a real expected valid proof and adversarial rejection, records
  actual outcomes, and exits with failure on missing inputs or mismatch. CI definition existence
  never changes `formal/qualification.json` to qualified.
- Environment protection/review/branch restrictions and the qualified runner itself must be
  administered before enabling that workflow. It has not been run in this session.
- `infra/validate_metadata.py` checks locked image/action forms, loopback Compose exposure,
  workflow default permissions and honest qualification metadata.
- Self-hosting README/qualification explicitly mark Kubernetes/Firecracker/Ray and 128/1000-worker
  scale as not implemented/not run. No magical capacity or portable snapshot claim.

### Runbooks

`docs/DEPLOYMENT.md` explains local setup, exact inputs, image publishing prerequisites, private
AWS bootstrap, role/secret provisioning, one-shot migration success checks, staged desired counts,
TLS, private console/Temporal dependencies and qualified CI inputs.

`docs/OPERATIONS.md` covers recorded releases, immutable migrations, role separation and secret
rotation, admission and uncertainty, outbox/lease/usage monitoring, RDS/S3 restoration with artifact
integrity, fencing/reconciliation, destructive-downgrade avoidance, acceptance boundaries and
measured scale/fault-injection qualification. SLOs remain explicit unverified acceptance targets.

## Final verification

```
.venv/bin/python -m ruff check infra migrations tests/test_infrastructure.py
.venv/bin/python infra/validate_metadata.py
.venv/bin/python -m pytest tests/test_infrastructure.py -q
/tmp/physharness-infra-tools/terraform -chdir=infra/terraform/aws fmt -check
/tmp/physharness-infra-tools/terraform -chdir=infra/terraform/aws validate -no-color
```

Results: lint clean; metadata valid; **10 passed, 1 skipped** (live PostgreSQL endpoint absent);
Compose config valid; Terraform format and provider validation successful. No running image,
Temporal cluster, AWS resource, live kernel or sustained worker-capacity result was fabricated.

Relevant primary interfaces inspected:
- https://github.com/temporalio/samples-server/tree/main/compose (server, schema/namespace commands)
- https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task_execution_IAM_role.html
- https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/UsingWithRDS.SSL.html
- https://releases.hashicorp.com/terraform/
- Official GitHub action tag APIs and public Docker Hub/GHCR manifest APIs, recorded on 2026-09-14.
