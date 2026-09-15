# Deployment

The repository contains runnable configuration scaffolding, not a qualified production deployment.
The AWS configuration has passed Terraform validation; the local Compose file has passed Compose
configuration validation. This host has no running Docker daemon or dedicated PostgreSQL endpoint,
so image builds, container startup, live database migration, cloud deployment and live proof checks
have not been executed here. No Terraform plan or apply has been run.

## Recorded inputs

`infra/images.lock.json` records registry-resolved image digests for Python 3.12.13, uv 0.11.14,
PostgreSQL 16, Temporal Server/admin-tools 1.31.0 and Temporal UI 2.49.1. These are manifest metadata
pins, not claims that the images have passed execution/security qualification. Refresh tags and
digests together under review; never replace them with `latest`. Application deployments require
an independently built/published image digest. The Dockerfile has no default base-image fallback.

Terraform is validated with 1.16.2 and AWS provider 6.10.0. The provider lock contains signed
checksums for Linux amd64 and macOS arm64. Review provider/toolchain updates as explicit changes.
The checked-in AWS RDS public CA bundle has its source and SHA-256 in
`infra/certs/rds-global-bundle.json`; it contains no private credential.

## Local PostgreSQL and Temporal

Requirements: Docker Engine, Docker Compose (the standalone `docker-compose` command also works),
Python 3.12 and the project environment. The initial setup contains no model-provider key and will
not launch research workers by default.

```sh
uv sync --locked --all-extras
uv run python infra/prepare_local.py
# The command refuses to overwrite .env; it creates role-scoped random local tokens.
docker-compose --env-file .env config --quiet
docker-compose --env-file .env up -d
# Build the application, migrate canonical tables, then start the API:
docker-compose --env-file .env --profile app up --build -d
```

The `.env` file is created with mode 0600 and is ignored by git. It includes separate local
researcher/reviewer/operator tokens, a random PostgreSQL password, exact image references and
an empty price table. Open it locally to use the correct role token; do not paste it into logs,
issues or a deployment manifest. It is Compose configuration, not a shell script.

PostgreSQL persists in `postgres-data`; the API's local artifacts persist in `artifacts`. Temporal
has separate databases in that development PostgreSQL server. A supported `temporalio/server`
image runs only after the one-shot admin-tools schema job succeeds. Namespace creation is a
separate bounded job. Database initialization SQL runs only on a new PostgreSQL volume; version
upgrades require the upstream database/schema migration procedure, not removal of stored data.
This is a single-node development topology, not Temporal HA.

Development endpoints bind only loopback:

- API: `http://127.0.0.1:8000`; `/healthz` proves process availability, not dependency health.
- PostgreSQL: `127.0.0.1:5432` (Compose applications use hostname `postgres`).
- Temporal: `127.0.0.1:7233`; Temporal UI: `http://127.0.0.1:8080`.
- Console: run `npm ci && npm run dev` in `console`; configure its API connection and role token.

To enable real research deliberately, add `OPENAI_API_KEY` and a reviewed exact-model
`PHYSHARNESS_MODEL_PRICES` JSON object to the private environment. Experiment records select the
model; the worker never chooses a default replacement. E2B tools additionally require the key and
an exact separately qualified template ID. Then start both application and worker profiles:

```sh
docker-compose --env-file .env --profile app --profile worker up --build -d
```

The worker command is `python -m physharness.worker`. Missing provider/pricing/template inputs
remain unavailable. Starting the worker is not evidence of accepted research or scale.

## Managed AWS control plane

`infra/terraform/aws` provisions:

- A VPC with two AZs, separate public/NAT, private application and database subnets.
- An internal HTTPS ALB, private Fargate API and worker services, and a one-shot migration task.
- Private, encrypted Multi-AZ RDS PostgreSQL with TLS required, 35-day backups, deletion
  protection, explicit minor version and an RDS-managed administrative secret.
- A private, versioned, KMS-encrypted canonical artifact bucket; application IAM has no object
  deletion permission. TLS is required by bucket policy.
- Separate task/execution IAM roles for API, worker and migrations, exact secret-ARN access,
  CloudWatch logs and scoped artifact access. Provider credentials go only to the research worker.

Temporal Cloud or another separately managed compatible Temporal service is an explicit input.
The worker uses TLS and the supplied Temporal API-key secret. This module does not provision or
pretend to qualify a production Temporal cluster. TLS-only model/AWS egress and Temporal port
7233 are allowed through NAT; fine-grained destination enforcement requires an additional reviewed
egress proxy/firewall. RDS accepts 5432 only from the task security group. API ingress arrives only
from the internal ALB. No task or database receives a public IP.

The module does not create a VPN, corporate-network attachment, DNS record, ACM certificate,
container registry, Temporal account, secret values, or qualified proof-acceptance fleet. Supply
and review these dependencies. In particular, the Docker/Landlock acceptance driver cannot be
assumed to run inside an ordinary Fargate task. Acceptance remains unavailable until its qualified
Linux boundary is provisioned and integrated separately.

### Bootstrap sequence

1. Build the API/worker image for **linux/amd64**, using the Python/uv digests in the image lock,
   run image tests, publish to the chosen registry, and record the resulting image digest. The
   image includes Alembic, E2B and numerical extras; it contains no API keys. For example, pass
   `--build-arg PYTHON_IMAGE=<pinned-reference>` and `--build-arg UV_IMAGE=<pinned-reference>` to
   `docker build --platform linux/amd64`. This repository's CI builds but does not publish images.
2. Provision a private, encrypted, versioned Terraform state bucket with restricted operator
   access. Copy `backend.hcl.example` to a private config and use S3 lockfile locking. Do not put
   credentials in that file. Use short-lived AWS operator credentials, not application secrets.
3. Create the required Secrets Manager secret containers out of band. Their ARNs, not secret
   values, are Terraform inputs. Application and schema-owner database credentials are separate;
   neither should be the RDS administrator. Keep both service desired counts at zero during
   bootstrap. Populate the auth-token secret with the actual token-to-Principal JSON format.
4. Copy `terraform.tfvars.example` to an ignored private `*.auto.tfvars` file. Replace every
   placeholder, including the exact RDS minor release supported in the chosen region, exact
   application image digest, private client ranges, ACM certificate, Temporal endpoint/namespace,
   price table and secret ARNs. Empty/unrecorded defaults are not substituted.
5. Initialize the reviewed state backend, validate and prepare a saved plan. Review that plan and
   its cost/security implications through the deployment approval process before applying it.
   The module provisions billable RDS, NAT gateways and other resources even with service counts
   zero. No application of this scaffolding was requested or performed during implementation.

```sh
terraform -chdir=infra/terraform/aws init -backend-config=/PRIVATE/PATH/backend.hcl
terraform -chdir=infra/terraform/aws fmt -check
terraform -chdir=infra/terraform/aws validate
terraform -chdir=infra/terraform/aws plan -out=/PRIVATE/PATH/deployment.tfplan
# Only after the concrete saved plan is approved:
terraform -chdir=infra/terraform/aws apply /PRIVATE/PATH/deployment.tfplan
```

6. From an authorized private-network administration environment, provision a schema-owner role
   and a restricted application role in the new `physharness` database. Grant the application
   role required DML and sequence privileges, including default privileges for future tables,
   but no role administration or schema creation. Set passwords through a secure administrative
   mechanism. Populate separate Secrets Manager database-URL values. Use
   `postgresql+psycopg://.../<database>?sslmode=verify-full`; the image supplies `/app/rds-ca.pem`
   and the ECS task sets `PGSSLROOTCERT` and `PGSSLMODE=verify-full`. Do not read secret values
   through Terraform, where they would enter state.
7. Launch the `migration_task_definition` output once using the private subnet and task security
   group outputs. Confirm `run-task` returned no failures, wait for task completion, and inspect
   the actual container exit code and logs. A task ARN or a stopped state alone is not success.
   The task runs `python -m alembic upgrade head` with only the schema-owner secret.
8. After successful migration, explicitly raise API/worker desired counts in reviewed Terraform
   inputs. Validate private routing/DNS/certificate identity, project authentication, S3 integrity,
   Temporal connectivity and fail-closed provider configuration. Secret rotation requires a new
   task deployment; running containers do not automatically receive new environment values.
9. Serve the built console behind an approved private HTTPS hosting path and configure its
   allowed API origin. Console hosting is deliberately outside this AWS module; do not make
   the artifact bucket public to serve it.

## CI and qualification

All external GitHub Actions are pinned to verified commit SHAs. CI installs from `uv.lock`, runs
Python lint/tests and deployment metadata validation, runs the console tests/build, builds the
actual application image, validates Terraform without a backend, and defines a real PostgreSQL
migration test in a disposable database schema. No deployment/publishing credentials are supplied
to pull-request CI. The main unit job excludes explicitly external integration/Lean tests.

`qualified-lean.yaml` is manual and runs only on a self-hosted Linux runner labeled
`physharness-qualified`, under the `verification-qualification` environment. Configure required
reviewers and protected-branch restrictions for that environment before enabling its runner.
Only trusted repository revisions may run there. Operator-owned qualification, manifest and
reviewed case files must be provided with complete SHA-256 pins. The script executes the actual
Comparator verifier, requires both a valid expected proof and an adversarial expected rejection,
and fails if inputs/runtime are absent or outcomes differ. It never marks unit-test mocks as a
kernel run or invents semantic review. The workflow being present is not qualification evidence.

## Later self-hosting

See `infra/selfhost/README.md` and its explicit unqualified record. Kubernetes, Firecracker,
Ray/KubeRay, snapshot migration and 128/1,000-worker capacity remain separate future deployment
and acceptance work. The development Compose stack does not stand in for those claims.

Primary interface references:
[Temporal supported Compose examples](https://github.com/temporalio/samples-server/tree/main/compose),
[ECS execution-role permissions](https://docs.aws.amazon.com/AmazonECS/latest/developerguide/task_execution_IAM_role.html),
[RDS TLS identity verification](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/UsingWithRDS.SSL.html).

## Optional worker VM policy

`PHYSHARNESS_WORKER_WORKSPACE` defaults to JSON `null`, which leaves model shell/file tools
unavailable. To enable them, supply a private operator-reviewed JSON object with `template_id`,
`environment_digest`, `qualification_report_sha256`, `timeout_seconds`, `cost_bound_usd`, and
`cost_source`. The environment must match the exact experiment target. The positive cost bound
must cover the configured VM lifetime; no pricing is inferred. The qualification hash must refer
to a real independently inspected report, not a placeholder chosen to pass schema validation.
Keep `E2B_API_KEY` in the worker secret environment; never put it in this policy or guest files.

Compose forwards the policy only to the worker. Terraform's nullable `worker_workspace` input
serializes the same record into worker configuration. This records operator inputs; neither
Terraform validation nor schema validation qualifies a VM image. Worker integration and cleanup
contracts are in [VM_WORKSPACES.md](VM_WORKSPACES.md). Unknown VM invoices retain the reserved cost
until an operator reconciles them, even after confirmed destruction releases capacity.
