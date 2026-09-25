# Calibration to cooperative transition (operator runbook)

This is a read-only preparation note. Root operates the live records and makes the semantic and deployment decisions. Do not rerun or resume the completed calibration. Preserve its one-shot marker, log, database, and artifacts. Run the following only after the calibration launcher has exited and no worker/verifier container is active. Each exclusive output is one-shot: if it already exists, inspect and validate it instead of repeating that command. Do not print token files or the private export.

Use these local paths in a fresh shell (the pilot scripts and files are pinned by the calibration freeze):

```sh
cd /Users/kieranpi/Desktop/Projects/PhysHarnessV2/.worktrees/formal-research-loop
export PILOT_STATE="$PWD/.state/hardening-final-2026-09-24"
export PILOT_MANIFEST="$PILOT_STATE/manifest-calibration.json"
export PILOT_QUAL="$PWD/work/pilot-qualification-2026-09-23/attempt-hardening-20260924-01/qualification-review.json"
export PYTHONPATH="$PWD/src:$PWD/work/hardening-final-2026-09-24"
.venv/bin/python work/hardening-final-2026-09-24/pilot_launch.py check --manifest "$PILOT_MANIFEST" --qualification "$PILOT_QUAL"
```

The current status snapshot says the supervisor completed, one task and one session completed, no receipt exists, and the canonical ledger spent $1.47013 with zero active workers, reserved cost/tokens, and uncertain operations. The experiment itself is still `queued`. Reopen the canonical ledger and pause the experiment with the issued *operator* identity, after independently confirming the launcher is no longer running. This code reads the token internally and prints no credential:

```sh
.venv/bin/python - <<'PY'
import json
import os
from pathlib import Path
from physharness.bootstrap import build_service
from pilot_runner import load_manifest, operator_settings

manifest = load_manifest(Path(os.environ["PILOT_MANIFEST"]))
attempt = manifest["attempts"][-1]
private = Path(attempt["private_directory"])
result = json.loads(Path(attempt["result_file"]).read_text())
settings, actor = operator_settings(manifest, attempt)
service = build_service(settings)
experiment = service.get_record("experiment", attempt["experiment_id"], actor)
ledger = service.ledger(attempt["experiment_id"], actor)
tasks = service.list_records("task", actor, attempt["experiment_id"])
receipts = service.list_records("verification", actor, attempt["experiment_id"])
assert result["status"] == "completed" and result["experiment_id"] == attempt["experiment_id"]
assert experiment["status"] in {"queued", "running"}
assert not experiment.get("budget_reconciliation_required")
assert ledger["active_workers"] == ledger["tokens_reserved"] == ledger["uncertain_operations"] == 0
assert ledger["reserved_cost_usd"] == "0"
assert tasks and all(t["status"] in {"completed", "failed", "cancelled"} for t in tasks)
assert all(r["status"] not in {"queued", "running", "pending"} for r in receipts)
paused = service.transition_experiment(
    attempt["experiment_id"], "pause", experiment["revision"], actor,
    f"hardening-pause:{attempt['experiment_id']}",
)
assert paused["status"] == "paused"
print(json.dumps({"status": paused["status"], "spent_cost_usd": ledger["spent_cost_usd"], "receipt_count": len(receipts)}))
PY
```

The pause is a state change, not a proof decision. Export verifies every immutable artifact byte and full terminal session/continuation lineage; it refuses an active or uncertain attempt. Both outputs remain private:

```sh
umask 077
.venv/bin/python work/exponential-pilot-2026-09-24/audit_export.py \
  --manifest "$PILOT_MANIFEST" --label hardening-calibration-1 \
  > "$PILOT_STATE/attempts/hardening-calibration-1/audit-command-result.json"
.venv/bin/python work/exponential-pilot-2026-09-24/evaluate.py \
  --manifest "$PILOT_MANIFEST" --label hardening-calibration-1 \
  --output "$PILOT_STATE/attempts/hardening-calibration-1/evaluation.json"
```

Inspect the private audit and evaluation, including exact receipt count, terminal lineage, usage IDs, and ledger. Zero receipts means no independently verified target proof. The task/run `completed` statuses mean that the model ended and resources drained; they are not scientific acceptance. The model produced an unverified argument and an auxiliary lemma. Count it as a partial result and record the root's decision to advance only after this review. The legacy launch gate requires the exact private file `attempts/hardening-calibration-1/advance-decision.json` with `{"decision":"advance","experiment_id":"aa0bd292-db10-4dfd-abde-b2269f9b87a8"}`. If root chooses to advance, create it exclusively with mode 0600:

```sh
.venv/bin/python - <<'PY'
import json
import os
from pathlib import Path
path = Path(os.environ["PILOT_STATE"]) / "attempts/hardening-calibration-1/advance-decision.json"
decision = {"decision": "advance", "experiment_id": "aa0bd292-db10-4dfd-abde-b2269f9b87a8"}
fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
with os.fdopen(fd, "w") as stream:
    json.dump(decision, stream, separators=(",", ":"))
PY
```

Never infer approval from supervisor completion.

With the calibration paused, export validated, and root advance review recorded, prepare the cooperative phase. `prepare` reopens all prior canonical ledgers and exports, retains the calibration attempt in the new manifest, and computes the new attempt ceiling as `52 - actual settled calibration spend` (currently $50.52987). It creates an isolated project, DB, artifacts, bundle and role credentials; it makes zero model calls.

```sh
.venv/bin/python work/hardening-final-2026-09-24/pilot_prepare.py prepare \
  --spec "$PILOT_STATE/prepare-spec-draft.json" --phase cooperative \
  --prior-manifest "$PILOT_MANIFEST"
.venv/bin/python work/hardening-final-2026-09-24/pilot_runner.py inspect \
  --manifest "$PILOT_STATE/manifest-cooperative.json"
```

Root must review the new problem record against the exact challenge SHA-256 `9b356ee2f2ea86fa860a332bb7d93bafd2d8ed49ced2941732147cb5c6304dc8`, assumptions, target theorem, environment digest, and withheld complete reference/controls. The new project gives a different target digest by design, because it includes its campaign identity. A prior semantic approval is not portable across projects. After root writes a substantive decision rationale to the private new-attempt file `semantic-review-rationale.txt`, only the issued *reviewer* principal may record that decision. `operator_settings` can parse the scoped identities, but its verification registry does not exist yet, so remove that configuration when constructing this review-only service:

```sh
.venv/bin/python - <<'PY'
import hashlib
import json
import os
from pathlib import Path
from physharness.bootstrap import build_service
from pilot_runner import load_manifest, operator_settings

state = Path(os.environ["PILOT_STATE"])
manifest = load_manifest(state / "manifest-cooperative.json")
attempt = manifest["attempts"][-1]
prepared = json.loads((state / "prepared-cooperative.json").read_text())
private = Path(attempt["private_directory"])
rationale = (private / "semantic-review-rationale.txt").read_text().strip()
assert rationale
settings, _ = operator_settings(manifest, attempt)
reviewer = settings.auth_tokens[(private / "reviewer.token").read_text().strip()]
assert reviewer.role == "reviewer" and reviewer.project_id == attempt["project_id"]
service = build_service(settings.model_copy(update={"verification_registry": None}))
problem = service.get_record("problem", prepared["problem_revision_id"], reviewer)
assert problem["target_digest"] == prepared["target_digest"]
assert hashlib.sha256(problem["formal_statement"].encode()).hexdigest() == manifest["challenge_sha256"]
assert problem["environment_digest"] == manifest["environment_digest"]
review = service.review_problem(
    problem["id"], "approved", rationale, reviewer,
    f"hardening-semantic-review:{problem['id']}",
)
fd = os.open(private / "semantic-review.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
with os.fdopen(fd, "w") as stream:
    json.dump(review, stream, separators=(",", ":"))
print(json.dumps({"review_id": review["id"], "decision": review["decision"]}))
PY
```

Do not assemble/activate merely because preparation succeeded.

The pinned Linux qualification at `$PILOT_STATE/qualification.json` binds the verifier image and resource profile, not a specific project. After the new semantic review, assemble the new problem-specific registry:

```sh
.venv/bin/python work/hardening-final-2026-09-24/pilot_prepare.py assemble-registry \
  --manifest "$PILOT_STATE/manifest-cooperative.json" \
  --record "$PILOT_STATE/prepared-cooperative.json" \
  --qualification "$PILOT_STATE/qualification.json" \
  --resources "$PWD/formal/verifier-resources.json"
```

Root then independently reviews that registry, source-bound qualification, worker capacity report, calibration export and spend, target controls, and the cooperative four-worker scope. If activation is justified, write a separate `deployment-decision-cooperative.json` with the same decision schema as calibration, the **new** registry SHA-256, mechanical status `satisfied`, production qualification `false`, and scope/limits specific to this private two-root, four-worker attempt. The launch wrapper checks decision and registry hash equality. Finally freeze the cooperative inputs and verify continuity with the calibration freeze:

```sh
.venv/bin/python work/hardening-final-2026-09-24/pilot_launch.py freeze \
  --manifest "$PILOT_STATE/manifest-cooperative.json" --qualification "$PILOT_QUAL"
.venv/bin/python work/hardening-final-2026-09-24/pilot_launch.py check \
  --manifest "$PILOT_STATE/manifest-cooperative.json" --qualification "$PILOT_QUAL"
```

`freeze` creates `source-freeze-cooperative.json` exclusively. It requires exact cross-phase hashes for source, verifier/formal assets and operator wrappers; do not overwrite it to accommodate drift. For the later, separately authorized root launch, the one-shot path is `pilot_launch.py launch --manifest "$PILOT_STATE/manifest-cooperative.json" --qualification "$PILOT_QUAL" --label hardening-cooperative-1`. The runner rechecks the freeze under global and attempt locks, previous export/advance gate, canonical budget, model and target contract, and private deployment decision before starting or reserving. Do not run that command as part of transition preparation.
