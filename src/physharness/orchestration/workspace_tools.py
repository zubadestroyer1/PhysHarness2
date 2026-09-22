"""Model-facing VM tools: fixed authority, lazy budgeted allocation, explicit cleanup."""

from decimal import Decimal

from pydantic import Field

from ..domain import Digest, StrictModel
from ..errors import HarnessError
from ..execution import CommandRequest


class WorkspacePolicy(StrictModel):
    template_id: str = Field(min_length=1)
    environment_digest: Digest
    qualification_report_sha256: Digest
    timeout_seconds: int = Field(ge=1, le=86400)
    cost_bound_usd: Decimal = Field(gt=0, decimal_places=6, allow_inf_nan=False)
    cost_source: str = Field(min_length=1)


class WorkspaceTools:
    def __init__(self, broker, policy: WorkspacePolicy):
        self.broker, self.policy, self.workspace = broker, policy, None
        task = broker.service.get_record("task", broker.task_id, broker.actor)
        experiment = broker.service.get_record("experiment", task["experiment_id"], broker.actor)
        target = broker.service.get_record("problem", experiment["problem_id"], broker.actor)
        if target["environment_digest"] != policy.environment_digest:
            raise HarnessError(
                "WORKSPACE_ENVIRONMENT_MISMATCH",
                "Configured VM environment differs from the exact research target.",
            )

    async def _ensure(self):
        if self.workspace is None:
            self.workspace = await self.broker.provision(
                cost_bound_usd=str(self.policy.cost_bound_usd),
                operation_id=f"workspace:{self.broker.task_id}:{self.broker.holder}",
            )
        return self.workspace

    async def run(self, arguments, operation_id):
        workspace = await self._ensure()
        return await self.broker.run(
            workspace["id"],
            expected_execution_id=workspace["execution_id"],
            request=CommandRequest(
                operation_id=operation_id,
                argv=arguments["argv"],
                cwd=arguments["cwd"],
                timeout_seconds=arguments["timeout_seconds"],
                max_output_bytes=65536,
            ),
        )

    async def write(self, arguments, operation_id):
        workspace = await self._ensure()
        return await self.broker.upload_file(
            workspace["id"],
            expected_execution_id=workspace["execution_id"],
            path=arguments["path"],
            data=arguments["content"].encode(),
            operation_id=operation_id,
        )

    async def checkpoint(self, arguments, operation_id):
        workspace = await self._ensure()
        return await self.broker.export_workspace(
            workspace["id"],
            expected_execution_id=workspace["execution_id"],
            operation_id=operation_id,
        )

    def unresolved(self):
        task = self.broker.service.get_record("task", self.broker.task_id, self.broker.actor)
        return [
            row
            for row in self.broker.service.list_records(
                "workspace", self.broker.actor, task["experiment_id"]
            )
            if row["task_id"] == self.broker.task_id
            and row.get("shared_worker_slot_id") == self.broker.worker_slot_id
            and row["status"] != "destroyed"
        ]

    async def close(self):
        # Cleanup precedes lease release and never fabricates a provider invoice.
        if self.workspace is not None:
            observed = self.broker.inspect(self.workspace["id"])
            if observed["status"] != "destroyed":
                await self.broker.destroy(
                    observed["id"],
                    expected_execution_id=observed["execution_id"],
                    operation_id=f"cleanup:{self.broker.holder}",
                    actual_cost_usd=None,
                )
        if self.unresolved():
            raise HarnessError(
                "WORKSPACE_RECONCILIATION_REQUIRED",
                "Unresolved VM allocation retains its shared worker slot.",
            )

    def register(self, register):
        register(
            "run_command",
            {
                "argv": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                "cwd": {"type": "string"},
                "timeout_seconds": {
                    "type": "number",
                    "exclusiveMinimum": 0,
                    "maximum": self.policy.timeout_seconds,
                },
            },
            self.run,
            "Execute scientific code or Lean inside the pinned isolated VM. "
            "Use cwd='.' for the upload/checkpoint root or a relative subdirectory. "
            "Files outside that root are not included in workspace checkpoints. "
            "The real exit status and diagnostics are evidence, not proof acceptance.",
        )
        register(
            "write_workspace_file",
            {"path": {"type": "string"}, "content": {"type": "string"}},
            self.write,
            "Write a bounded file in the isolated scientific workspace.",
        )
        register(
            "checkpoint_workspace",
            {},
            self.checkpoint,
            "Archive bounded regular workspace files as an immutable artifact. "
            "This is not a full VM memory snapshot.",
        )


def e2b_workspace_factory(policy: WorkspacePolicy):
    """Factory is control-plane configuration; no model can supply credentials or policy."""
    import os

    from ..execution.e2b import E2BSandboxProvider
    from .workspaces import WorkspaceBroker

    def construct(service, actor, task_id, holder, fence, worker_slot_id):
        key = os.environ.get("E2B_API_KEY")
        if not key:
            raise HarnessError("VM_CREDENTIALS_REQUIRED", "E2B credentials are not configured.")
        broker = WorkspaceBroker(
            service,
            actor=actor,
            task_id=task_id,
            holder=holder,
            fence=fence,
            worker_slot_id=worker_slot_id,
            provider_spec={
                "provider": "e2b",
                "template_id": policy.template_id,
                "timeout_seconds": policy.timeout_seconds,
            },
            provider_factory=lambda *, journal: E2BSandboxProvider(
                api_key=key,
                template_id=policy.template_id,
                timeout_seconds=policy.timeout_seconds,
                journal=journal,
            ),
        )
        return WorkspaceTools(broker, policy)

    return construct
