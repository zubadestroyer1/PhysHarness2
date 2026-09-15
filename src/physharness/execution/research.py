"""Durable host-command broker and replay-driven JS execution inside a provider VM.

No model JavaScript is evaluated in the control-plane process or in Node vm.
A provider VM is mandatory. Its template must contain Node and no control-plane
credentials or mounted host paths. VM networking must be disabled by its provider.
"""

from __future__ import annotations

import json
from typing import Any

from .responses import ToolDispatcher
from .storage import CommandJournal
from .types import CommandRequest, ExecutionError, SandboxExecutor, digest


class ResearchProgramRunner:
    def __init__(
        self,
        journal: CommandJournal,
        *,
        executor: SandboxExecutor | None = None,
        dispatcher: ToolDispatcher | None = None,
        max_commands: int = 100,
        timeout_seconds: float = 30,
    ):
        if max_commands < 1 or timeout_seconds <= 0:
            raise ValueError("Program command and wall-time limits must be positive")
        self.journal = journal
        self.executor = executor
        self.dispatcher = dispatcher or ToolDispatcher()
        self.max_commands = max_commands
        self.timeout_seconds = timeout_seconds

    async def command(
        self, program_id: str, operation_id: str, name: str, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        replay = self.journal.begin(program_id, operation_id, name, arguments)
        if replay is not None:
            return replay
        result = await self.dispatcher.dispatch(name, arguments, f"{program_id}:{operation_id}")
        self.journal.complete(program_id, operation_id, result)
        return result

    async def run(self, program_id: str, source: str) -> Any:
        executor = self.executor
        if executor is None or not executor.capabilities.available:
            raise ExecutionError(
                "PROVIDER_UNAVAILABLE",
                "Research JavaScript requires a configured isolated provider VM",
                remediation="Configure an exact E2B Node template; Python journal is available",
            )
        if executor.capabilities.isolation != "provider_vm":
            raise ExecutionError(
                "UNSAFE_RUNTIME", "Model JavaScript may execute only inside an isolated provider VM"
            )
        # Provider capability is supplemented by an explicit deny-network guarantee.
        if not getattr(executor, "network_disabled", False):
            raise ExecutionError("UNSAFE_RUNTIME", "Research VM must disable network egress")
        if len(source.encode()) > 131072:
            raise ExecutionError("PROGRAM_LIMIT", "Program exceeds source-size limit")
        existing = self.journal.begin(
            program_id, "__program_identity__", "program", {"digest": digest(source)}
        )
        if existing is None:
            self.journal.complete(program_id, "__program_identity__", {"accepted": True})
        for _ in range(self.max_commands + 1):
            replay = self.journal.export(program_id)
            pending = [record for record in replay if record["status"] != "completed"]
            if pending:
                raise ExecutionError(
                    "OPERATION_UNCERTAIN", "Program contains an unreconciled host operation"
                )
            records = [r for r in replay if r["operation_id"] != "__program_identity__"]
            wrapper = self._wrapper(source, records)
            result = await executor.run(
                CommandRequest(
                    argv=["node", "--input-type=module", "-e", wrapper],
                    timeout_seconds=self.timeout_seconds,
                    max_output_bytes=65536,
                )
            )
            if result.exit_code or result.stdout_truncated:
                raise ExecutionError(
                    "PROGRAM_FAILED", "JavaScript subprocess failed or exceeded output limit"
                )
            try:
                message = json.loads(result.stdout)
                kind = message["kind"]
            except (ValueError, KeyError, TypeError) as exc:
                raise ExecutionError(
                    "PROGRAM_PROTOCOL_ERROR", "Research VM did not return a valid broker message"
                ) from exc
            if kind == "result":
                return message.get("value")
            if kind != "command":
                raise ExecutionError(
                    "PROGRAM_FAILED", "JavaScript program failed; inspect VM output artifact"
                )
            if len(records) >= self.max_commands:
                raise ExecutionError(
                    "PROGRAM_LIMIT", "Research program exhausted host-command budget"
                )
            op, name, args = (
                message.get("operation_id"),
                message.get("name"),
                message.get("arguments"),
            )
            if (
                not isinstance(op, str)
                or not op
                or op.startswith("__")
                or not isinstance(name, str)
                or not isinstance(args, dict)
            ):
                raise ExecutionError("PROGRAM_PROTOCOL_ERROR", "Malformed broker command identity")
            await self.command(program_id, op, name, args)
        raise ExecutionError("PROGRAM_LIMIT", "Program did not finish within replay limit")

    @staticmethod
    def _wrapper(source: str, records: list[dict[str, Any]]) -> str:
        # This is untrusted code in a VM. The broker treats every emitted command
        # as untrusted input and authorizes it through ToolDispatcher.
        header = f"const replay = {json.dumps(records, allow_nan=False)};\n"
        header += f"const source = {json.dumps(source)};\n"
        return (
            header
            + """
const send = value => new Promise(resolve => {
  process.stdout.write(JSON.stringify(value), resolve);
});
const canonical = value => {
  if (Array.isArray(value)) return '[' + value.map(canonical).join(',') + ']';
  if (value && typeof value === 'object') {
    return '{' + Object.keys(value).sort().map(k =>
      JSON.stringify(k)+':'+canonical(value[k])).join(',') + '}';
  }
  return JSON.stringify(value);
};
const host = async (operation_id, name, args) => {
  const previous = replay.find(r => r.operation_id === operation_id);
  if (previous) {
    if (previous.command !== name || canonical(previous.arguments) !== canonical(args)) {
      throw new Error('COMMAND_MISMATCH');
    }
    return previous.result;
  }
  await send({kind:'command', operation_id, name, arguments: args});
  process.exit(0);
};
try {
  const AsyncFunction = Object.getPrototypeOf(async function(){}).constructor;
  const value = await new AsyncFunction('host', source)(host);
  await send({kind:'result', value: value === undefined ? null : value});
} catch (error) { await send({kind:'error', message: String(error)}); process.exitCode = 1; }
"""
        )
