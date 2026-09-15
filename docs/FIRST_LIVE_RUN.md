# First reviewed research run

This workflow prepares a real model attempt and a subsequent lemma-reuse experiment. The
engineering tests use a real proof toolchain and explicitly mocked model transports. No live
model result, expert review, production sandbox qualification or worker-fleet capacity is implied.

The remaining scientific inputs are an exact model/API configuration and a reviewed target in
the built library environment. An operator must also approve the execution boundary from its
actual evidence before configuring scientific acceptance. A passing engineering report is not
automatically that approval. See [verification](VERIFICATION.md) and the
[formal environment](FORMAL_ENVIRONMENT.md).

## Prepare the trusted inputs

Run from the repository checkout with Python 3.12 and `uv sync --locked --all-extras`. Initialize
private state with `uv run phys init` if it does not already exist. All commands below use the
same configured database, artifact store and identity store as the API. They require no running
HTTP server. `phys init` refuses to overwrite existing identity files.

Put private inputs under `.state/runs/<run-name>/`. Copy the approved `Challenge.lean` there.
The target includes its definitions and explicit assumptions; its selected theorem may contain
the proof hole being solved. Unreviewed definition holes remain a separate acceptance blocker.
Preserve the exact bytes that the expert will inspect, including the theorem's qualified name.

Prepare a `project/` directory containing trusted Lake configuration and the toolchain file.
For the physics image, copy `formal/lakefile.physics.toml` as `project/lakefile.toml`,
`formal/lake-manifest.physics.json` as `project/lake-manifest.json`, and `formal/lean-toolchain`.
Only include additional trusted source files intentionally. Candidate sources, credentials,
snapshots and caches do not belong in this directory. The libraries must exist in the selected
image; choosing an image without the required modules cannot enable them by metadata alone.

Create the exact environment bytes from the built image's metadata. Substitute real paths and
the SHA-256 of the metadata file you inspected:

```sh
uv run phys prepare-environment PATH_TO_BUILT_IMAGE_METADATA.json \
  --image-metadata-sha256 INSPECTED_METADATA_SHA256 \
  --project-directory .state/runs/first/project \
  --include lakefile.toml --include lake-manifest.json --include lean-toolchain \
  --output-file .state/runs/first/environment.json
```

Use the separately exported physics image metadata for targets importing physics libraries.
The core image metadata is suitable only for its built standard-library environment. Output
files are exclusive: changes create a fresh file and a new target revision, never an overwrite.

Copy [the run-plan template](../examples/research_runs/plan.template.json) into this directory
as `plan.json`. Fill in the exact model identifier, problem text, assumptions, definitions,
source provenance, theorem name and a deliberate resource envelope. The template is an input
schema example; its strings are not reviewed scientific content. Paths are relative to the plan
directory. Parent traversal, child symlinks, oversized/non-regular files, unknown configuration
fields and invalid model parameters fail before preparation creates records.

```sh
export PHYSHARNESS_TOKEN="$(cat .state/researcher.token)"
uv run phys prepare-run .state/runs/first/plan.json
```

Retain the returned `problem_id`, `experiment_id`, `target_digest` and preparation artifact ID.
Preparation creates an inactive experiment and a pending target; it makes zero model calls.
The same run ID and inputs return the same records. Changed input cannot reuse an old
idempotency key. A partially interrupted preparation can be retried with the identical inputs.

## Review and configure acceptance

An expert inspects the original source, formal statement, definitions, selected theorem,
quantifiers, domains, units/conventions, regularity, boundary conditions and assumptions. Record
the written rationale in a private file. The reviewer then supplies their separate identity:

```sh
export PHYSHARNESS_TOKEN="$(cat .state/reviewer.token)"
uv run phys review-target PROBLEM_ID \
  --target-digest INSPECTED_SEMANTIC_TARGET_DIGEST \
  --rationale-file .state/runs/first/review.txt \
  --idempotency-key first-target-review
```

This is an explicit human decision, not an instruction to approve an unseen theorem. The digest
must equal the exact inspected canonical revision. Replacing a review makes earlier queued
checks and old receipts inapplicable to the new approval until reverified; historical receipts
retain their original attribution. Human reviewer tokens stay outside model workspaces.

Build the bundle using the operator identity:

```sh
export PHYSHARNESS_TOKEN="$(cat .state/operator.token)"
uv run phys bundle-target PROBLEM_ID \
  --environment-file .state/runs/first/environment.json \
  --project-directory .state/runs/first/project \
  --destination .state/verifier/bundles/first
```

The command checks the canonical source/environment identities and every trusted project file.
It returns a manifest hash and creates no review or proof receipt. Configure either the existing
single-bundle settings or `PHYSHARNESS_VERIFICATION_REGISTRY` pointing to an operator-owned
registry. The two configurations are mutually exclusive. Registry entries each contain an
exact `problem_revision_id` and `ComparatorConfig`; see
[registry configuration](VERIFICATION.md#multiple-target-bundles).

The operator supplies `LinuxQualification` from actual reviewed execution evidence: image,
driver, launcher, seccomp and report hashes, Linux boundary, and independent-kernel capability.
Do not substitute placeholder hashes or promote the checked-in engineering observations into
an approval. Unknown revisions, changed pins or incompatible kernels produce blocked results.

## Preflight and run

Supply `OPENAI_API_KEY` privately to the worker process. Set `PHYSHARNESS_MODEL_PRICES` to a JSON
mapping from the exact configured model IDs to `input_usd_per_million`,
`output_usd_per_million` and a pricing `source`. These values are recorded with resource usage;
prices are operator inputs, not guesses in the repository. Do not put credentials in plans,
model parameters, source artifacts or version control.

```sh
export PHYSHARNESS_TOKEN="$(cat .state/operator.token)"
uv run phys check-run EXPERIMENT_ID
uv run phys run-team EXPERIMENT_ID --concurrency 1 --max-tasks 8 --timeout-seconds 1800
```

`check-run` reports missing inputs together and exits nonzero when blocked. Its
`ready_for_live_attempt` status means configuration preflight passed; it does not probe model
availability, execute a candidate, approve the host, or promise a solution. The first actual
request can still fail because of provider/model-specific restrictions. Typed local validation
catches malformed values before queuing; model-specific feature support remains provider-owned.

The finite supervisor uses canonical leases, artifacts, budget reservations and task records.
It processes the bounded verification queue, including candidates submitted during execution.
Models can wait for a receipt without polling through additional paid model turns. Candidate
submission requests the independent kernel required for lemma sharing. The legacy request field
`publication=True` selects this assurance; it grants no permission to publish a result.

Run this local supervisor without a concurrent Temporal dispatcher for the same experiment if
you intend its finite task/concurrency limits to describe the whole run. A distributed Temporal
deployment still enforces the experiment's central envelope, but another supervisor can recruit
work beyond one local manifest's subset. Repeated delivery uses the same canonical root IDs and
leases; it cannot silently change a command's meaning.

Optional E2B workspace tools require a separately configured worker workspace policy and E2B
credentials/template. With no worker workspace, the model has canonical research, retrieval,
artifact and verification tools but no arbitrary shell or local exploratory Lean process.
Generated scientific code runs only through the configured isolated workspace provider.

Inspect canonical tasks, sessions, claims, receipts and ledger in the console/API. A completed
model turn or team report is execution completion, not a proved theorem. Only exact canonical
verification receipts establish proof status. Reports identify live versus mocked transports,
failed tasks, pending receipts, unresolved external costs and non-cancellable checks. If a
supervisor times out while an isolated checker thread is still running, shutdown may wait for
that check's own deadline; the report cannot certify that external execution stopped.

## Reuse and controlled parallelism

For a second target, create a new run ID/problem and obtain a new target review. Retain the
same exact environment bytes when its trusted dependencies are unchanged. Add its bundle as a
second registry entry and restart the service processes that load the registry. The CLI loads
the configured registry on each invocation. The model can retrieve the accepted lemma's source and provenance through
`search_knowledge` and `read_dependency_bundle`; it must recompose that source into the new
candidate. The final verifier checks the complete new proof. Imported binary caches and a
previous receipt alone do not prove the new theorem.

After a successful single-worker attempt and reuse run, use an `independent` plan with multiple
explicit model configurations, enlarge the recorded envelope, and raise `--concurrency` within
that envelope. The task bound must cover the root team and any desired descendants. Helpers,
collaborators and competing branches share the central authority; children cannot manufacture
new budget. Models choose their mathematics and may decline decomposition or tools.

First compare small teams at equal cost and equal elapsed time. Current mocked overlap and
failure tests validate coordination behavior, not live throughput. The 128-worker/72-hour and
1,000-worker qualification gates remain separate future experiments.

## Stop and retain evidence

Cancel or pause through the experiment API when stopping allocation; a process exit alone does
not cancel durable tasks or reconcile provider invoices. Retain accepted artifacts and uncertain
reservations for reconciliation. Export via `phys export` and verify artifact hashes with
`phys validate-export`; publication additionally requires a clean proof rebuild and review.

Once local VM tests and experiments finish, stop the dedicated development VM to release RAM:

```sh
COLIMA_HOME=/private/tmp/physharness-colima colima stop
```

This targets only the dedicated profile used for this implementation. Keep its disk/artifacts
for reuse; do not start or stop unrelated user VMs. Shut down cloud workers through their
canonical provider lifecycle so destruction and remaining costs are recorded.
