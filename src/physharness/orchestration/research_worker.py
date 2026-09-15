"""Authority-preserving integration of models, scientific records and resource accounting."""

import asyncio
import inspect
import logging
import os
from contextlib import nullcontext, suppress
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import select

from ..domain import (
    ArtifactCreate,
    BranchCreate,
    Principal,
    TaskCreate,
    canonical_json,
    digest_json,
    new_id,
)
from ..errors import HarnessError
from ..execution import (
    ExecutionError,
    ModelConfig,
    ResponsesRuntime,
    RuntimeCheckpoint,
    RuntimeLimits,
    ToolDispatcher,
)
from ..execution.parameters import validate_responses_parameters
from ..memory import PortableMemory
from ..storage import RecordRow
from ..worker_authority import worker_effects
from .pricing import ModelPrice

log = logging.getLogger(__name__)


class CanonicalRuntimeStore:
    """Every native state is an immutable artifact, with fenced current-session metadata."""

    def __init__(self, service, actor, experiment_id, task_id, holder, fence):
        self.service, self.actor, self.experiment_id = service, actor, experiment_id
        self.task_id, self.holder, self.fence = task_id, holder, fence

    async def save(self, checkpoint):
        # Cancellation may still retain uncertain evidence; stale holders cannot
        # publish any canonical checkpoint. Each command verifies this binding.
        with worker_effects(
            self.actor, self.task_id, self.holder, self.fence, require_active=False
        ):
            self._save_checkpoint(checkpoint)

    def _save_checkpoint(self, checkpoint):
        checkpoint.verify()
        data = checkpoint.model_dump(mode="json")
        artifact = self.service.create_artifact(
            ArtifactCreate(
                experiment_id=self.experiment_id,
                kind="native_checkpoint",
                content=canonical_json(data),
                media_type="application/json",
                provenance={"task_id": self.task_id, "session_id": checkpoint.session.id},
            ),
            self.actor,
            f"runtime-artifact:{digest_json(data)}",
        )

        def action(session, op):
            self.service._fenced(session, self.task_id, self.holder, self.fence)
            row = session.scalar(
                select(RecordRow).where(
                    RecordRow.project_id == self.actor.project_id,
                    RecordRow.kind == "session",
                    RecordRow.payload["native_record_id"].as_string() == checkpoint.session.id,
                )
            )
            if row and (
                row.payload.get("task_id") != self.task_id
                or row.payload.get("experiment_id") != self.experiment_id
            ):
                raise HarnessError(
                    "SESSION_SCOPE", "Native session already belongs to another task."
                )
            values = {
                "experiment_id": self.experiment_id,
                "task_id": self.task_id,
                "native_record_id": checkpoint.session.id,
                "runtime": checkpoint.session.runtime,
                "model": checkpoint.session.model.model_dump(mode="json"),
                "status": checkpoint.session.status,
                "checkpoint_artifact_id": artifact["id"],
                "input_tokens": checkpoint.session.input_tokens,
                "output_tokens": checkpoint.session.output_tokens,
            }
            return (
                self.service._replace(session, row, values)
                if row
                else self.service._insert(session, "session", self.actor, values)
            )

        self.service._execute(
            self.actor, f"runtime-save:{digest_json(data)}", "runtime.save", data, action
        )

    async def load(self, session_id):
        rows = self.service.list_records("session", self.actor, self.experiment_id)
        matches = [
            r
            for r in rows
            if r["native_record_id"] == session_id and r.get("task_id") == self.task_id
        ]
        if len(matches) != 1:
            raise HarnessError(
                "SESSION_NOT_FOUND", "Native continuation state is missing or ambiguous."
            )
        import json

        data = json.loads(
            self.service.artifact_content(matches[0]["checkpoint_artifact_id"], self.actor)
        )
        checkpoint = RuntimeCheckpoint.model_validate(data)
        checkpoint.verify()
        return checkpoint


def research_tools(service, agent, branch_id, *, task_context=None, workspace_tools=None):
    dispatcher = ToolDispatcher()

    def check_worker():
        if task_context:
            with service.db.sessions() as session:
                service._active(session, agent.experiment_id, agent)
                service._fenced(session, **task_context)

    def register(name, properties, handler, description):
        async def wrapped(args, operation_id):
            try:
                check_worker()
                with worker_effects(agent, **task_context) if task_context else nullcontext():
                    result = handler(args, operation_id)
                    return await result if inspect.isawaitable(result) else result
            except HarnessError as error:
                if error.code in {"STALE_LEASE", "EXPERIMENT_NOT_ACTIVE", "EXPERIMENT_DEADLINE"}:
                    raise ExecutionError(
                        error.code, str(error), operation_id=operation_id
                    ) from error
                # Expected tool rejections are observable to the model and canonical logs.
                log.warning(
                    "Research tool rejected: %s", error.code, extra={"operation_id": operation_id}
                )
                return error.envelope()

        dispatcher.register(
            name,
            {
                "type": "object",
                "properties": properties,
                "required": list(properties),
                "additionalProperties": False,
            },
            wrapped,
            description,
        )

    register(
        "checkpoint_context",
        {
            "approach": {"type": "string"},
            "unresolved_obligations": {"type": "array", "items": {"type": "string"}},
            "summary": {"type": ["string", "null"]},
            "previous_checkpoint_id": {"type": ["string", "null"]},
            "evidence_ids": {"type": "array", "items": {"type": "string"}},
            "max_bytes": {"type": "integer", "minimum": 1, "maximum": 8388608},
            "max_estimated_tokens": {"type": "integer", "minimum": 1},
        },
        lambda a, k: PortableMemory(service).checkpoint(
            branch_id, agent, k, **a, **(task_context or {})
        ),
        "Preserve portable scientific context with the exact target, assumptions and obligations. "
        "The summary is attributed and unverified; "
        "byte/token-estimate limits never truncate the core.",
    )
    register(
        "restore_context",
        {"checkpoint_id": {"type": "string"}},
        lambda a, k: PortableMemory(service).restore(
            a["checkpoint_id"], agent, expected_branch_id=branch_id
        ),
        "Restore a portable checkpoint after checking target, review and current evidence. "
        "Stale checkpoints require a fresh context from canonical records.",
    )
    register(
        "restart_brief",
        {},
        lambda args, key: service.restart_brief(branch_id, agent),
        "Retrieve target assumptions, open obligations and artifacts with their evidence status.",
    )
    register(
        "search_knowledge",
        {"query": {"type": "string"}, "type_query": {"type": "string"}},
        lambda a, k: service.search_knowledge(
            agent.experiment_id, a["query"], agent, a["type_query"]
        ),
        "Retrieve reusable mechanically accepted premises with exact environment and assumptions.",
    )
    register(
        "read_dependency_bundle",
        {"claim_id": {"type": "string"}},
        lambda a, k: service.knowledge_bundle(agent.experiment_id, a["claim_id"], agent),
        "Retrieve accepted lemma source, assumptions, target and receipt. "
        "Recomposition and verification of your complete proof are required.",
    )
    register(
        "read_artifact",
        {"artifact_id": {"type": "string"}},
        lambda a, k: {"content": service.artifact_content(a["artifact_id"], agent).decode()},
        "Read hash-checked evidence within the experiment scope.",
    )
    register(
        "store_artifact",
        {"kind": {"type": "string"}, "content": {"type": "string"}},
        lambda a, k: service.create_artifact(
            ArtifactCreate(
                experiment_id=agent.experiment_id,
                kind=a["kind"],
                content=a["content"],
                provenance={"branch_id": branch_id},
            ),
            agent,
            k,
        ),
        "Store source or findings. Use kind lean_source for candidates. "
        "This does not verify a claim.",
    )
    register(
        "verify_candidate",
        {"artifact_id": {"type": "string"}},
        lambda a, k: service.verify_candidate(
            agent.experiment_id, a["artifact_id"], True, agent, k
        ),
        "Queue independent-kernel proof acceptance against the exact reviewed target. "
        "The publication request flag requires independent replay for reusable evidence; "
        "it never approves publication or scientific novelty.",
    )
    register(
        "inspect_verification",
        {"receipt_id": {"type": "string"}},
        lambda a, k: service.get_record("verification", a["receipt_id"], agent),
        "Inspect a queued, blocked, rejected or verified receipt without assuming success.",
    )

    async def wait_for_verification(args, operation_id):
        deadline = asyncio.get_running_loop().time() + args["timeout_seconds"]
        while True:
            check_worker()
            receipt = service.get_record("verification", args["receipt_id"], agent)
            remaining = deadline - asyncio.get_running_loop().time()
            if receipt["status"] != "queued" or remaining <= 0:
                return receipt
            await asyncio.sleep(min(0.1, remaining))

    register(
        "wait_for_verification",
        {
            "receipt_id": {"type": "string"},
            "timeout_seconds": {"type": "number", "exclusiveMinimum": 0, "maximum": 30},
        },
        wait_for_verification,
        "Wait up to 30 seconds for a canonical receipt without paid model polling. "
        "A still-queued result is unresolved; a verifier worker must process it.",
    )
    register(
        "fork_branch",
        {
            "title": {"type": "string"},
            "objective": {"type": "string"},
            "relation": {"type": "string", "enum": ["helper", "collaborator", "competing"]},
            "model_index": {"type": ["integer", "null"], "minimum": 0, "maximum": 99},
        },
        lambda a, k: service.create_branch(
            agent.experiment_id, BranchCreate(**a, parent_id=branch_id), agent, k
        ),
        "Create an optional helper, collaborator or competing approach "
        "under the same resource envelope.",
    )
    register(
        "delegate",
        {
            "branch_id": {"type": "string"},
            "objective": {"type": "string"},
            "dependency_ids": {"type": "array", "items": {"type": "string"}},
        },
        lambda a, k: service.create_task(TaskCreate(**a), agent, k),
        "Queue bounded work when useful; children cannot increase the "
        "experiment resource envelope.",
    )
    register(
        "send_message",
        {
            "recipient_id": {"type": "string"},
            "content": {"type": "string"},
            "artifact_ids": {"type": "array", "items": {"type": "string"}},
        },
        lambda a, k: service.send_message(
            branch_id, a["recipient_id"], a["content"], a["artifact_ids"], agent, k
        ),
        "Send an attributed idea to another branch; messages do not confer proof status.",
    )
    if workspace_tools is not None:
        workspace_tools.register(register)
    return dispatcher


class ResearchTaskExecutor:
    def __init__(
        self, service, *, prices: dict, runtime_factory=None, limits=None, workspace_factory=None
    ):
        self.service = service
        self.prices = {name: ModelPrice.model_validate(price) for name, price in prices.items()}
        self.runtime_factory = runtime_factory or ResponsesRuntime
        self.live_runtime = runtime_factory is None or runtime_factory is ResponsesRuntime
        self.limits = limits or RuntimeLimits()
        self.workspace_factory = workspace_factory

    async def execute(self, task_id: str, project_id: str):
        actor = Principal(id="research-controller", project_id=project_id, role="operator")
        task = self.service.get_record("task", task_id, actor)
        if task["status"] in {"completed", "failed", "blocked"}:
            return {"task_id": task_id, "status": task["status"]}
        prior_sessions = [
            record
            for record in self.service.list_records("session", actor, task["experiment_id"])
            if record["task_id"] == task_id
        ]
        if prior_sessions:
            raise HarnessError(
                "RECOVERY_RECONCILIATION_REQUIRED",
                "A prior native session exists; do not repeat a possibly billed model request.",
                remediation=(
                    "Inspect the durable checkpoint and outstanding reservations "
                    "before explicit continuation."
                ),
            )
        experiment = self.service.get_record("experiment", task["experiment_id"], actor)
        branch = self.service.get_record("branch", task["branch_id"], actor)
        model = branch.get("model_configuration", experiment["models"][0])
        if model["runtime"] != "responses":
            raise HarnessError(
                "RUNTIME_NOT_QUALIFIED",
                "This distributed worker requires the qualified Responses contract.",
                remediation=(
                    "Native SDKs remain separately usable under their explicit "
                    "capability restrictions."
                ),
            )
        # Validate before acquiring a lease or reserving a worker slot, including
        # direct HTTP/Temporal dispatches that did not pass through run preflight.
        try:
            model_config = ModelConfig(
                model=model["model"],
                parameters=validate_responses_parameters(model["parameters"]),
            )
            runtime_limits = RuntimeLimits.model_validate(
                experiment.get("runtime_limits") or self.limits.model_dump()
            )
        except (ExecutionError, ValidationError):
            raise HarnessError(
                "INVALID_CONFIG",
                "The model configuration or runtime limits are invalid.",
                status=422,
            ) from None
        if model["model"] not in self.prices:
            raise HarnessError(
                "MODEL_PRICE_REQUIRED",
                "A recorded price is required before requesting paid model work.",
            )
        price = self.prices[model["model"]]
        holder = new_id()
        slot = self.service.reserve_resources(experiment["id"], "0", 1, actor, f"slot:{holder}")
        try:
            lease = self.service.acquire_task(task_id, holder, 60, actor, f"lease:{holder}")
        except Exception:
            self.service.settle_resources(slot["id"], "0", False, actor, f"unused-slot:{holder}")
            raise
        agent = Principal(
            id=holder,
            project_id=project_id,
            role="agent",
            experiment_id=experiment["id"],
            branch_id=branch["id"],
        )
        store = CanonicalRuntimeStore(
            self.service, actor, experiment["id"], task_id, holder, lease["fence"]
        )
        reservations = {}
        settled = set()

        async def accounting(event):
            if event.kind == "generation_started":
                inp, out = (
                    event.payload["input_tokens_reserved"],
                    event.payload["output_tokens_reserved"],
                )
                reservation = self.service.reserve_resources(
                    experiment["id"],
                    price.cost(inp, out),
                    0,
                    actor,
                    f"model-reserve:{event.operation_id}",
                    tokens=inp + out,
                )
                reservations[event.operation_id] = reservation["id"]
            elif event.kind == "usage":
                if event.operation_id not in reservations:
                    raise HarnessError(
                        "UNRESERVED_USAGE", "A model returned usage without a known reservation."
                    )
                inp, out = event.payload["input_tokens"], event.payload["output_tokens"]
                self.service.settle_resources(
                    reservations[event.operation_id],
                    price.cost(inp, out),
                    False,
                    actor,
                    f"model-settle:{event.operation_id}",
                    actual_tokens=inp + out,
                )
                settled.add(event.operation_id)
            self.service.create_artifact(
                ArtifactCreate(
                    experiment_id=experiment["id"],
                    branch_id=branch["id"],
                    kind="runtime_event",
                    content=canonical_json(event.model_dump(mode="json")),
                    media_type="application/json",
                    provenance={"task_id": task_id, "price": price.model_dump(mode="json")},
                ),
                actor,
                f"runtime-event:{digest_json(event.model_dump(mode='json'))}",
            )

        running, renewal, workspace_tools = None, None, None
        cleanup_attempted = False

        async def cleanup():
            nonlocal cleanup_attempted
            if workspace_tools is not None and not cleanup_attempted:
                cleanup_attempted = True
                await workspace_tools.close()

        try:

            def bind_slot(session, op):
                self.service._fenced(session, task_id, holder, lease["fence"])
                row = self.service._get(session, "task", task_id, actor)
                return self.service._replace(session, row, {"worker_slot_id": slot["id"]})

            self.service._execute(
                actor,
                f"bind-slot:{holder}",
                "task.bind-slot",
                {"task_id": task_id, "holder": holder, "fence": lease["fence"], "slot": slot["id"]},
                bind_slot,
            )
            if self.workspace_factory:
                workspace_tools = self.workspace_factory(
                    self.service, actor, task_id, holder, lease["fence"], slot["id"]
                )
                policy = workspace_tools.policy.model_dump(mode="json")

                def bind_policy(session, op):
                    self.service._fenced(session, task_id, holder, lease["fence"])
                    row = self.service._get(session, "task", task_id, actor)
                    return self.service._replace(session, row, {"workspace_policy": policy})

                self.service._execute(
                    actor,
                    f"workspace-policy:{holder}",
                    "task.workspace-policy",
                    policy,
                    bind_policy,
                )
            runtime = self.runtime_factory(
                store=store,
                dispatcher=research_tools(
                    self.service,
                    agent,
                    branch["id"],
                    task_context={"task_id": task_id, "holder": holder, "fence": lease["fence"]},
                    workspace_tools=workspace_tools,
                ),
                event_sink=accounting,
            )
            prompt = canonical_json(
                {
                    "objective": task["objective"],
                    "allowed_model_configurations": experiment["models"],
                    "research_brief": self.service.restart_brief(branch["id"], agent),
                    "instructions": (
                        "Choose your mathematical approach freely. Tools and delegation "
                        "are optional. Report assumptions and unresolved gaps accurately. "
                        "Only an independent receipt establishes proof status."
                    ),
                }
            )
            running = asyncio.create_task(runtime.start(prompt, model_config, runtime_limits))

            async def renew():
                tick = 0
                while True:
                    await asyncio.sleep(10)
                    tick += 1
                    self.service.renew_task(
                        task_id, holder, lease["fence"], 60, actor, f"renew:{holder}:{tick}"
                    )

            renewal = asyncio.create_task(renew())
            done, _ = await asyncio.wait([running, renewal], return_when=asyncio.FIRST_COMPLETED)
            if renewal in done:
                await renewal
            result = await running
            artifact = self.service.create_artifact(
                ArtifactCreate(
                    experiment_id=experiment["id"],
                    branch_id=branch["id"],
                    kind="research_output",
                    content=result.output_text,
                    provenance={
                        "task_id": task_id,
                        "session_id": result.session.id,
                        "model": model,
                    },
                ),
                actor,
                f"task-output:{task_id}:{holder}",
            )
            await cleanup()
            completed = self.service.finish_task(
                task_id,
                holder,
                lease["fence"],
                [artifact["id"]],
                "completed",
                actor,
                f"task-complete:{holder}",
            )
            return {
                "task_id": task_id,
                "status": completed["status"],
                "artifact_id": artifact["id"],
            }
        except BaseException as error:
            if running is not None:
                running.cancel()
                with suppress(BaseException):
                    await running
            log.exception("Research task failed", extra={"task_id": task_id})
            try:
                await cleanup()
            except BaseException:
                log.exception(
                    "VM cleanup failed; shared capacity remains reserved",
                    extra={"task_id": task_id},
                )
            for operation_id, reservation_id in reservations.items():
                if operation_id not in settled:
                    self.service.settle_resources(
                        reservation_id, None, True, actor, f"uncertain:{operation_id}"
                    )
            # Preserve failure evidence even when cancellation or a lost lease prohibits completion.
            failure_artifact = self.service.create_artifact(
                ArtifactCreate(
                    experiment_id=experiment["id"],
                    branch_id=branch["id"],
                    kind="execution_failure",
                    content=canonical_json(
                        {
                            "task_id": task_id,
                            "error_type": type(error).__name__,
                            "code": getattr(error, "code", "EXECUTION_FAILED"),
                            "message": "Inspect logs; external calls may need reconciliation.",
                        }
                    ),
                ),
                actor,
                f"failure:{holder}",
            )
            try:
                self.service.finish_task(
                    task_id,
                    holder,
                    lease["fence"],
                    [failure_artifact["id"]],
                    "blocked",
                    actor,
                    f"task-blocked:{holder}",
                )
            except HarnessError as state_error:
                log.warning(
                    "Failure evidence retained but task state could not change: %s",
                    state_error.code,
                    extra={"task_id": task_id},
                )
            raise
        finally:
            if renewal is not None:
                renewal.cancel()
                with suppress(BaseException):
                    await renewal
            unresolved = [
                row
                for row in self.service.list_records("workspace", actor, experiment["id"])
                if row.get("shared_worker_slot_id") == slot["id"] and row["status"] != "destroyed"
            ]
            self.service.settle_resources(
                slot["id"],
                None if unresolved else "0",
                bool(unresolved),
                actor,
                f"slot-finished:{holder}",
            )


class TeamRunLimits(BaseModel):
    """Validate supervisor limits before allocating any canonical tasks."""

    model_config = ConfigDict(extra="forbid")
    max_concurrency: int = Field(default=1, ge=1, le=100)
    max_tasks: int = Field(default=8, ge=1, le=1000)
    timeout_seconds: float = Field(default=300, gt=0, le=86400, allow_inf_nan=False)


class TeamRunManifest(TeamRunLimits):
    """Finite execution of explicit canonical tasks and their optional descendants."""

    experiment_id: str = Field(min_length=1)
    project_id: str = Field(min_length=1)
    mode: Literal["live", "replay"]
    task_ids: list[str] = Field(min_length=1, max_length=1000)
    include_delegated: bool = True
    process_verifications: bool = True
    max_verifications: int = Field(default=8, ge=0, le=1000)
    run_id: str = Field(default_factory=new_id, min_length=1)

    @field_validator("task_ids")
    @classmethod
    def unique_tasks(cls, values):
        if len(set(values)) != len(values) or any(not value.strip() for value in values):
            raise ValueError("Task IDs must be unique and nonempty")
        return values


class ResearchTeamRunner:
    """A bounded local supervisor over durable, independently leased canonical tasks.

    Temporal remains the distributed delivery mechanism. This runner is also useful
    for finite operator launches and deterministic integration replay. Losing this
    Python process never deletes child tasks or turns uncertain sessions into retries.
    """

    def __init__(self, service, *, executor: ResearchTaskExecutor):
        self.service, self.executor = service, executor
        self._verification_tasks: set[asyncio.Task] = set()

    def _records(self, kind, actor, experiment_id):
        cursor = None
        while True:
            page = self.service.page_records(kind, actor, experiment_id, 500, cursor)
            yield from page["items"]
            cursor = page["next_cursor"]
            if cursor is None:
                return

    async def run(self, manifest: TeamRunManifest | dict):
        manifest = TeamRunManifest.model_validate(manifest)
        actor = Principal(id="team-controller", project_id=manifest.project_id, role="operator")
        experiment = self.service.get_record("experiment", manifest.experiment_id, actor)
        if manifest.max_concurrency > experiment["budget"]["max_concurrency"]:
            raise HarnessError("TEAM_LIMIT", "Team concurrency exceeds the experiment envelope.")
        if manifest.mode == "live":
            if not self.executor.live_runtime or not os.environ.get("OPENAI_API_KEY"):
                raise HarnessError(
                    "LIVE_PROVIDER_REQUIRED", "Live runs require configured Responses credentials."
                )
        elif self.executor.live_runtime:
            raise HarnessError(
                "REPLAY_PROVIDER_REQUIRED", "Replay requires an explicitly injected mock provider."
            )
        roots = [self.service.get_record("task", task_id, actor) for task_id in manifest.task_ids]
        if any(task["experiment_id"] != experiment["id"] for task in roots):
            raise HarnessError("TASK_SCOPE", "Team tasks must belong to the manifest experiment.")
        if len(roots) > manifest.max_tasks:
            raise HarnessError("TEAM_LIMIT", "Explicit tasks exceed the finite task limit.")
        self.service.create_artifact(
            ArtifactCreate(
                experiment_id=experiment["id"],
                kind="team_run_manifest",
                media_type="application/json",
                content=manifest.model_dump_json(),
                provenance={"mode": manifest.mode, "run_id": manifest.run_id},
            ),
            actor,
            f"team-manifest:{manifest.run_id}",
        )
        initial_ids = {task["id"] for task in self._records("task", actor, experiment["id"])}
        root_branches = {task["branch_id"] for task in roots}
        outcomes, active, attempted = {}, {}, set()
        checks, checked_ids, verification_errors = {}, set(), []
        stop_reason = None
        deadline = asyncio.get_running_loop().time() + manifest.timeout_seconds

        def selected_tasks():
            descendants = set(root_branches)
            if manifest.include_delegated:
                branches = list(self._records("branch", actor, experiment["id"]))
                while True:
                    added = {b["id"] for b in branches if b.get("parent_id") in descendants}
                    if added <= descendants:
                        break
                    descendants.update(added)
            return [
                task
                for task in self._records("task", actor, experiment["id"])
                if task["id"] in manifest.task_ids
                or (
                    manifest.include_delegated
                    and task["branch_id"] in descendants
                    and (task["branch_id"] not in root_branches or task["id"] not in initial_ids)
                )
            ]

        async def cancel_active():
            for future in active:
                future.cancel()
            if active:
                await asyncio.gather(*active, return_exceptions=True)
            for task_id in active.values():
                outcomes[task_id] = {
                    "task_id": task_id,
                    "status": "blocked",
                    "code": "EXECUTION_CANCELLED",
                }
            active.clear()

        def verification_receipts():
            branches = {task["branch_id"] for task in selected_tasks()}
            return [
                receipt
                for receipt in self._records("verification", actor, experiment["id"])
                if receipt.get("branch_id") in branches
            ]

        async def verify(receipt_id):
            verifier = Principal(
                id="team-acceptance-worker", project_id=actor.project_id, role="verifier"
            )
            # Independent authority runs outside every model's worker_effects scope.
            return await asyncio.to_thread(self.service.process_verification, receipt_id, verifier)

        def retain_verifier(future):
            self._verification_tasks.discard(future)
            # Retrieve exceptions when the supervisor timed out before this checker.
            if not future.cancelled():
                future.exception()

        try:
            while True:
                state = self.service.get_record("experiment", experiment["id"], actor)["status"]
                if state not in {"queued", "running"}:
                    stop_reason = "EXPERIMENT_NOT_ACTIVE"
                    break
                if asyncio.get_running_loop().time() >= deadline:
                    stop_reason = "TEAM_TIMEOUT"
                    break
                selected = selected_tasks()
                if manifest.process_verifications and not checks:
                    for receipt in verification_receipts():
                        if (
                            receipt["status"] != "queued"
                            or receipt["id"] in checked_ids
                            or len(checked_ids) >= manifest.max_verifications
                        ):
                            continue
                        checked_ids.add(receipt["id"])
                        future = asyncio.create_task(verify(receipt["id"]))
                        self._verification_tasks.add(future)
                        future.add_done_callback(retain_verifier)
                        checks[future] = receipt["id"]
                        break  # One independent checker at a time per finite supervisor.
                task_states = {
                    task["id"]: task["status"]
                    for task in self._records("task", actor, experiment["id"])
                }
                for task in selected:
                    task_id = task["id"]
                    if task_id in attempted or task_id in outcomes:
                        continue
                    if task["status"] in {"completed", "failed", "blocked"}:
                        outcomes[task_id] = {"task_id": task_id, "status": task["status"]}
                        continue
                    if (
                        len(active) >= manifest.max_concurrency
                        or len(attempted) >= manifest.max_tasks
                    ):
                        break
                    if any(task_states.get(dep) != "completed" for dep in task["dependency_ids"]):
                        continue
                    attempted.add(task_id)
                    future = asyncio.create_task(self.executor.execute(task_id, actor.project_id))
                    active[future] = task_id
                if not active and not checks:
                    pending = [task for task in selected if task["id"] not in outcomes]
                    if pending:
                        stop_reason = (
                            "TEAM_TASK_LIMIT"
                            if len(attempted) >= manifest.max_tasks
                            else "DEPENDENCIES_PENDING"
                        )
                    break
                # Poll canonical cancellation while model calls are in flight.
                completed, _ = await asyncio.wait(
                    [*active, *checks],
                    timeout=min(0.25, max(0, deadline - asyncio.get_running_loop().time())),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for future in completed:
                    if future in checks:
                        receipt_id = checks.pop(future)
                        try:
                            future.result()
                        except Exception as error:
                            verification_errors.append(
                                {
                                    "receipt_id": receipt_id,
                                    "code": getattr(error, "code", "VERIFICATION_FAILED"),
                                }
                            )
                        continue
                    task_id = active.pop(future)
                    try:
                        outcomes[task_id] = future.result()
                    except Exception as error:
                        outcomes[task_id] = {
                            "task_id": task_id,
                            "status": "blocked",
                            "code": getattr(error, "code", "EXECUTION_FAILED"),
                        }
            await cancel_active()
        except BaseException:
            await cancel_active()
            raise
        remaining = [task["id"] for task in selected_tasks() if task["id"] not in outcomes]
        pending_receipts = [
            receipt["id"] for receipt in verification_receipts() if receipt["status"] == "queued"
        ]
        if pending_receipts and not stop_reason:
            stop_reason = "VERIFICATION_PENDING"
        summary = {
            "run_id": manifest.run_id,
            "experiment_id": experiment["id"],
            "mode": manifest.mode,
            "evidence_level": "live_provider" if manifest.mode == "live" else "mock_provider",
            "status": "completed"
            if not stop_reason
            and all(outcome["status"] == "completed" for outcome in outcomes.values())
            else "blocked",
            "stop_reason": stop_reason,
            "outcomes": list(outcomes.values()),
            "remaining_task_ids": remaining,
            "attempted_tasks": len(attempted),
            "verification_receipts": verification_receipts(),
            "verification_errors": verification_errors,
            "pending_verification_ids": pending_receipts,
            "verification_worker_continues": bool(checks),
            "ledger": self.service.ledger(experiment["id"], actor),
            "scientific_acceptance": "requires_independent_receipts_and_review",
        }
        artifact = self.service.create_artifact(
            ArtifactCreate(
                experiment_id=experiment["id"],
                kind="team_run_report",
                content=canonical_json(summary),
                media_type="application/json",
                provenance={"mode": manifest.mode, "run_id": manifest.run_id},
            ),
            actor,
            f"team-report:{manifest.run_id}:{digest_json(summary)}",
        )
        return {**summary, "artifact_id": artifact["id"]}
