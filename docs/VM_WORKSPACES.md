# E2B workspace durability

The adapter uses the installed `e2b==2.49.1` asynchronous Python SDK. Its contracts and mocked provider behavior have been tested; no live VM, snapshot, fork, pause, or paid provider request has been made. `workspace_capabilities["live_qualified"]` is therefore false. A configured capability describes an implemented interface, not completed cloud qualification.

## Three different recovery mechanisms

| Operation | Preserved state | Execution identity | Requirements |
| --- | --- | --- | --- |
| Portable workspace export / restore | Regular file contents and relative paths | Caller supplies an existing destination VM | Qualified credentialless Python 3 template; bounded archive |
| Native pause / resume | Provider-managed memory and filesystem | Same sandbox ID | Durable journal, explicit operation ID, provider availability |
| Native snapshot / restore | Provider-managed snapshot state | New sandbox ID on restore | Durable journal, operator-qualified pinned snapshot reference |
| Native fork | Provider-managed memory and filesystem at fork | New child sandbox ID; source remains independent | Durable journal, verified source and child no-egress configuration |

Portable archives omit empty directories, timestamps, owners, modes, executable bits, symlinks, hardlinks, devices, processes, open connections, and provider credentials. File permissions on restore are `0600`; created directories use `0700`. A portable archive is not a VM snapshot or a runtime/model conversation checkpoint.

The SDK has real `pause(keep_memory=True)`, instance/class `connect(on_resume="restore")`, `create_snapshot()`, and `fork(count=1)` methods. Fork returns a list whose elements can be sandbox objects **or exceptions**, which the adapter checks. SnapshotInfo contains `snapshot_id` and `names`; it has no immutable build hash field. These contracts are documented in the [primary async SDK source](https://github.com/e2b-dev/E2B/blob/main/packages/python-sdk/e2b/sandbox_async/main.py) and [provider data models](https://github.com/e2b-dev/E2B/blob/main/packages/python-sdk/e2b/sandbox/sandbox_api.py). Implementation was checked against local 2.49.1 source, not inferred from older reference pages.

## File archive interface

Import the new types directly from `physharness.execution.e2b`:

```python
from physharness.execution.e2b import E2BSandboxProvider, WorkspaceArchive
from physharness.execution.storage import CommandJournal

vm = E2BSandboxProvider(
    api_key=explicit_api_key,
    template_id=qualified_template_id,
    workspace_root="/home/user/workspace",
    journal=CommandJournal("vm-operations.sqlite"),
)
# create() allocates a real, billable VM; run only after provider qualification.
await vm.create()
identity = vm.execution_id
await vm.upload_file("src/example.py", b"print(42)\n", expected_execution_id=identity)
content = await vm.download_file("src/example.py", expected_execution_id=identity)
archive = await vm.export_workspace(expected_execution_id=identity)
# Persist archive.to_bytes() and archive.sha256 in the canonical artifact store.
verified = WorkspaceArchive.from_bytes(archive.to_bytes(), sha256=archive.sha256)
await destination.restore_workspace(verified, expected_execution_id=destination.execution_id)
```

`WorkspaceArchive.build({relative_path: bytes})` creates deterministic UTF-8 JSON, format `physharness.workspace.v1`, with sorted file entries containing `path`, base64 `data`, and a SHA-256 for each file. `sha256` covers the exact canonical archive bytes. `from_bytes` requires the expected outer hash and rejects noncanonical representations, duplicate entries, unsupported fields/types, malformed base64, wrong file hashes, and files that shadow parent directories. Archive hashes detect corruption; they are not signatures and require a trusted expected hash.

Version 1 limits are **65,536 archive bytes, 32,768 bytes per file, and 64 files**. Paths are at most 256 UTF-8 bytes. Larger workspaces fail explicitly. A future streamed artifact transport should introduce a versioned contract instead of silently truncating this one. `upload_file` returns the SHA-256 of the canonical single-file archive.

Transfers invoke adapter-authored Python via the genuine SDK `commands.run` interface. Input is bounded, shell-quoted JSON/base64 data; guest output is parsed as data. The helper runs `python3 -I`, opens root and path components with directory descriptors and `O_NOFOLLOW`, rejects hardlinks and nonregular files, and atomically replaces individual files. It does not use unrestricted tar/zip extraction or host-side execution of guest code. SDK `files.read/write` offer convenience transfer interfaces but do not provide the directory-descriptor confinement needed here.

A restore requires an empty workspace or exactly the same file contents. An identical completed restore is replayable; a conflicting workspace is rejected. Restore is **not transactional across multiple files**: interruption can leave partial files, which need reconciliation before retry. Export requires a quiescent guest; background processes can change files during traversal. The adapter serializes its own operations but does not claim an adversarial guest kernel or root user cannot tamper with its filesystem or helper. Run this only in a qualified credentialless VM; the VM boundary protects the host.

## Native state and replay

```python
checkpoint = await vm.pause(expected_execution_id=identity, operation_id="pause-001")
# Persist checkpoint.model_dump_json() in canonical storage.
await vm.resume(checkpoint, operation_id="resume-001")
child = await vm.fork(expected_execution_id=identity, operation_id="fork-001")
assert child.execution_id != identity

snapshot = await vm.snapshot(expected_execution_id=identity, operation_id="snapshot-001")
# Snapshot capture gates further source commands until explicitly resumed.
await vm.resume(snapshot, operation_id="resume-source-002")
```

`NativeWorkspaceCheckpoint` is a frozen, extra-fields-forbidden Pydantic record containing version, kind, execution ID, source template ID, optional snapshot ID, and a SHA-256 of its canonical state. Every native recovery validates its hash and source identity. A newly constructed provider without a local sandbox handle can `resume(checkpoint, operation_id=...)`; this uses the real class-level `AsyncSandbox.connect` and retains the checkpoint's sandbox ID. An already attached provider with a different ID is rejected. An expired/deleted source cannot be recreated through same-identity resume.

Native mutations require an explicit operation ID and an injected durable `CommandJournal` (or a compatible canonical-store implementation). Namespace is `e2b:<source execution ID>`. Replay arguments include template, workspace root, timeout and operation-specific inputs. Completed pause/snapshot results replay without another provider call. Completed fork/restore results replay the attached child in the same process only while that child remains usable. After losing or quarantining that handle, the journal retains the actual child ID and returns `NATIVE_RECONNECT_REQUIRED`; the controller must reconcile and explicitly reconnect that recorded identity. It must never call a new allocation as an automatic retry. Pending/error operations return `OPERATION_UNCERTAIN` on replay. Provider failure, cancellation or a crash between provider success and journal commit can leave resources to reconcile.

Returned fork/restore children are quarantined and their identities are synchronously persisted **before** awaiting metadata validation. `CommandJournal.observe` writes recovery evidence into the pending row's `result` without changing its status. Inspect `status` before interpreting `result`: a pending observation is not a successful allocation. Only successful validation followed by `complete` makes the child usable. If a malformed fork response returns multiple children, all known child identities appear in the observation's `children` list; the source is never adopted or killed as a child.

Validation failure or cancellation attempts bounded child cleanup and records whether destruction was confirmed. Failed or timed-out cleanup preserves the known identity and quarantine. Reopening the journal recovers this evidence and blocks another allocation under the same operation ID. Cancellation propagates as the original `CancelledError`, including when cleanup or recording the final observation fails. If the journal itself is unavailable, in-memory observations and exception notes retain recovery details; an unavailable durable store cannot guarantee survival of newly received evidence after process loss.

Native snapshot restore is:

```python
restored = await vm.restore_snapshot(
    snapshot,
    operation_id="restore-snapshot-001",
    pinned_snapshot_id=operator_qualified_snapshot_id,
)
```

The pin must exactly match the recorded snapshot ID. Untagged and `:latest` references are rejected. Other tags can also be retargeted: the adapter cannot prove immutability from this SDK response. The operator must qualify and preserve the exact reference; passing the pin explicitly attests that external requirement. Do not claim a snapshot is immutable merely because it has a version-looking tag. Source VM deletion is supported for snapshot restore, provided the snapshot still exists. Provider snapshots remain provider-owned; the JSON record does not contain their bytes.

All new VM creation supplies the configured exact template/snapshot, `allow_internet_access=False`, `secure=True`, and `envs={}`. Native fork cannot accept network overrides in this SDK: the adapter checks the source before forking and checks the returned child using actual SandboxInfo fields. It requires explicit `allow_internet_access=False` and rejects allowlists, rules, or egress proxies it cannot qualify. A failed child check triggers child termination and leaves an uncertain journal entry. Resume also verifies the resumed VM and terminates it on failed verification. No provider key is injected into guest environments. Native memory snapshots/forks inherit guest state, so templates and workspaces must already be credentialless.

Filesystem-only pause, forced reboot on resume, auto-resume, native snapshot deletion/GC, archive streaming, atomic multi-file restoration, and live cloud security/performance qualification are outside this adapter version. Although 2.49.1 has `keep_memory=False` and `on_resume="reboot"`, the SDK warns older control planes may ignore the reboot option; this implementation uses memory-preserving pause/restore only.

## Integration requirements

The generic execution protocols and capability records have not been expanded. Consumers must explicitly use the provider's `workspace_capabilities` mapping and methods. The controller should supply its canonical journal with synchronous `begin(namespace, operation_id, command, arguments)` and `complete(namespace, operation_id, result)` semantics, plus `observe(namespace, operation_id, observation)` for journals permitting native child allocations. It must persist archives plus trusted hashes, preserve native checkpoints and child IDs, reserve VM budget before native allocation, and add reconciliation/GC. SQLite is a development journal, not a second production source of truth. Do not enable provider operations from a model tool registry until those controls and a pinned credentialless template have been qualified.

## Canonical WorkspaceBroker

`physharness.orchestration.workspaces.WorkspaceBroker` implements the bounded operator lifecycle on `HarnessService`: provision, command execution, file upload, archive export, status inspection and confirmed destruction. It uses canonical `workspace` and `workspace_operation` records, existing resource reservations/budgets, current task leases, events, and the existing content-addressed artifact store. It creates no separate database or tables. The Responses worker integrates restricted model tools through `WorkspaceTools`; do not expose the operator broker itself to a model. Workspace metadata has a scoped read API.

```python
from physharness.execution.e2b import E2BSandboxProvider
from physharness.orchestration.workspaces import WorkspaceBroker

broker = WorkspaceBroker(
    service,
    actor=operator,
    task_id=task_id,
    holder=lease_holder,
    fence=lease_fence,
    provider_spec={
        "provider": "e2b",
        "template_id": qualified_template_id,
        "timeout_seconds": 60,
    },
    provider_factory=lambda *, journal: E2BSandboxProvider(
        api_key=explicit_api_key,
        template_id=qualified_template_id,
        timeout_seconds=60,
        journal=journal,
    ),
    worker_slot_id=controller_worker_slot_id,  # Omit for a separate VM worker slot.
)
workspace = await broker.provision(cost_bound_usd=operator_vm_cost_bound, operation_id="vm-create-1")
# Do not treat a replayed workspace as ready without checking its current status.
state = broker.inspect(workspace["id"])
result = await broker.run(
    workspace["id"], expected_execution_id=state["execution_id"], request=command_request,
)
export = await broker.export_workspace(
    workspace["id"], expected_execution_id=state["execution_id"], operation_id="vm-export-1",
)
# Actual cost is operator supplied when known; None keeps billing unresolved.
destroyed = await broker.destroy(
    workspace["id"], expected_execution_id=state["execution_id"], operation_id="vm-destroy-1",
    actual_cost_usd=None,
)
```

The factory is a synchronous, trusted `factory(*, journal)` that returns an **unallocated** provider. Allocation happens only in the broker's subsequent awaited `create()`. Its template, timeout, available VM isolation, and disabled-egress declaration must match the explicit provider specification. Factory configuration may contain credentials in its closure; the persisted provider specification cannot contain them.

Provision requires a positive, conservative, operator-supplied USD cost bound with micro-USD precision. No VM pricing or free tier is guessed. VM timeout must fit the experiment's remaining runtime. Workspace metadata, pending operation, cost reservation and concurrency accounting commit atomically **before** allocation. Standalone VMs reserve one worker slot. Shared-slot mode requires a current fenced task whose canonical `worker_slot_id` names an active same-experiment reservation with exactly one worker; uncertain or settled slots are rejected. Only one unresolved workspace may use that slot. The VM cost reservation then uses zero extra workers. A worker cannot claim a free slot through tool arguments.

**The controller must keep a shared worker slot held while any workspace referencing it is live, pending, or uncertain.** Destroying a VM settles only its cost reservation, never the parent slot. Before settling the parent in worker cleanup, inspect every canonical workspace with the same `shared_worker_slot_id`; anything except confirmed `destroyed` requires holding that slot and reconciliation. This dependency is a controller integration requirement; a separate operator call to the generic ledger can still bypass it.

Every dispatch and successful completion validates operator authority, project/task scope, experiment state, current holder/fence, workspace ownership, exact execution ID, and shared-slot binding. Cancellation blocks execution/upload/export. Destruction checks the same identity and current lease, but permits a cancelled experiment so its current worker can clean up before ending its lease. Lost leases cannot commit successful outcomes or settle reservations. No claim is made that SQL fencing can stop a remote process instantaneously: a lease lost during a provider call produces `reconciliation_required`, and the reservation remains held.

Operation fingerprints bind the exact command, content hash, cost inputs, provider specification, task holder/fence and shared-slot ID. Canonical pending records are not automatically retried. Repeated successful commands replay their stored results; provision replay returns the workspace's **current** canonical state, including `destroyed`. Missing local handles after restart require reconciliation rather than automatic reconnect/allocation. `inspect(workspace_id)` is an operator-only read of current canonical state; it grants no mutation authority and can be used after lease loss.

Uncertain provision, execution or destruction changes workspace/operation state to `reconciliation_required` and marks the VM reservation uncertain. A successful provider destruction followed by lease loss is recorded with `destruction_confirmed=true` but does not release resources. If the database also fails while recording uncertainty, the error includes workspace/operation/known VM IDs and destruction status; `broker.reconciliation_observations` retains that observation in memory. The original committed pending operation and reservation remain the recovery anchor. Persist those error details externally during a database outage. No cloud system can durably record a just-returned identity to an unavailable database without another durable channel.

Async cancellation during provision or a later broker operation records uncertainty and then re-raises the original `CancelledError`. A database failure while recording it is attached as an exception note and cannot turn cancellation into a normal model tool result. Consequently, a Responses runtime timeout remains an explicit `TIMEOUT`, and an explicit interrupt remains cancellation; neither starts another model generation. Pending tool execution remains uncertain in the runtime checkpoint. Cancellation observations do not settle reservations or authorize reuse, even if they contain confirmed destruction evidence; reconciliation must resolve the recorded lifecycle and billing under the proper authority.

`upload_file` takes `path`, bytes `data`, `operation_id` and the expected execution ID. `run` takes a `CommandRequest` and returns its JSON-serializable `CommandResult` dictionary. `export_workspace` stores verified archive bytes as a private `checkpoint` artifact and returns its artifact record/hash/identities; the workspace points to that artifact. The `CanonicalWorkspaceJournal` implements synchronous `begin`/`complete` with the same canonical operation records and pins native pause/snapshot results as private `native_checkpoint` artifacts. It serializes pending native work with ordinary workspace operations. It deliberately rejects `fork` and `restore_snapshot`: each child needs its own approved cost/concurrency lifecycle, which this broker version does not expose.

Broker restore/reconnect/adoption across leases, native child orchestration, automatic provider billing reconciliation and garbage collection remain explicit future integration work. Unknown provider outcomes never become successful cleanup merely because a timeout elapsed.

## Provider audit corrections

Creation now excludes concurrent creation and native resume/restore on the same adapter. Known preflight rejections leave an existing healthy VM usable; uncertain creation quarantines the adapter. If a native child is allocated but journal commit fails, its ID is retained in `native_child_observations`, cleanup is attempted with a bounded timeout, and an explicit uncertain error reports the ID and whether destruction was confirmed.

File-transfer timeout, cancellation and uncertain transport failure quarantine the VM and attempt bounded termination, recording `last_execution_observation`; subsequent work is refused until reconciliation. A **definitely completed** helper rejection, including the SDK's real `CommandExitException`, retains the VM. Files may have been partially changed, so inspect before retrying; preserving the VM does not imply a transactional rollback. Actual local-helper regression tests verify that refusing a conflicting restore does not erase previously stored files.

## Responses worker integration

`WorkspacePolicy` binds an exact template, target `environment_digest`, external
`qualification_report_sha256`, provider lifetime, positive cost bound and attributable cost source.
The report hash references operator qualification; the schema cannot establish that a VM is safe
or correctly configured. Supply and independently inspect that report before enabling real work.

Configure `PHYSHARNESS_WORKER_WORKSPACE` with the policy JSON. The control process holds the E2B
credential; generated code receives none. The model receives `run_command`, `write_workspace_file`
and `checkpoint_workspace`. Allocation is lazy and uses the task's reserved worker slot, so a
one-slot experiment can run its own scientific VM. Commands return genuine exit statuses and
bounded output; they cannot confer proof acceptance. No command runs on the control host if a
VM provider is missing.

The executor binds the shared slot under the current task fence, records the policy, and performs
cleanup before `finish_task` releases the lease. Confirmed destruction releases capacity even
when the invoice is unknown: the VM's cost reservation remains uncertain with zero workers and
its conservative cost bound remains held. The parent slot is retained whenever a referenced VM
is live, pending or uncertain. Later invoice settlement cannot release capacity twice.

A failed command can carry a provider cleanup observation. Only a literal confirmed-destruction
observation for the exact current VM, committed under the current lease, releases capacity.
False, mismatched or absent observations retain it. A known completed transfer refusal preserves
the VM for inspection/cleanup and replays as the same refusal. Public provider `cancel`/`close`
quarantine before awaiting termination, preventing concurrent reuse during an uncertain kill.

Scripted end-to-end tests cover shared-slot success and failed cleanup. They neither allocate
real VMs nor qualify provider billing, snapshot security, machine-loss restoration or sustained
scientific throughput. Workspace archive v1 remains deliberately small; streamed large artifact
transport and automated lease adoption are required for long-running campaigns.

Command working directories use the same root as file upload and archive export: `cwd="."`
selects the configured workspace root, and relative directories resolve beneath it. An explicit
absolute path selects that guest directory. This is a guest convenience contract, not filesystem
isolation within the VM; generated programs can access their authorized guest environment.
Checkpoints capture regular files under the configured root only. Outputs deliberately written
elsewhere must be copied or published explicitly before cleanup.

Qualified templates must precreate the configured workspace directory for command-first use.
The upload helper creates it when uploading the first file. Commands do not inject hidden
initialization calls; a missing working directory remains a visible guest execution error.
