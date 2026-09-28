# S1 Remediation: Tier 0 and the Society Lane Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the S1 audit's Tier-0 bugs, then turn the research society into a free-forming but directed research ecology with minimal scaffolding: shared substrate (an importable lemma store, stub skeletons, relevance-routed updates, event waits, library notes) replaces rules that decided nothing (labs, the status ladder, fidelity reviews, check-ins, task-count caps).

**Architecture:** Tier 0 (Tasks 1–4) repairs the workbench and tool errors and ships as its own PR. The society lane (Tasks 5–21) then replaces S1 society behaviour in place: policy fields are removed with a named-field refusal, commons state stays in JSON payloads (one new table, for library notes), and legacy (non-society) experiments stay byte-identical. The verifier stays the only arbiter; every new signal is substrate that agents may use or ignore.

**Tech Stack:** Python 3.12, pydantic v2, SQLAlchemy 2 (SQLite and PostgreSQL), Alembic, the OpenAI Responses runtime (mocked in tests), Lean 4 with Mathlib/Physlib in the local Docker workbench, pytest.

**Spec:** `work/society-s1/audit-2026-09-26/AUDIT.md` (merged in #33), with its reports `society.md`, `scaffolding.md`, `proofpath.md` and `tools.md` in the same directory. The binding rulings are summarised in this plan's Global Constraints.

## Global Constraints

- **G1.** Society changes REPLACE the S1 society behaviour; there is no dual "S1 vs lean" mode. Legacy experiments stay byte-identical: `test_legacy_catalog_unchanged`, `test_worker_legacy_prompt_unchanged` (`tests/test_society_tools.py`) and `test_legacy_discussion_delivery_shape_unchanged` (`tests/test_commons_discourse.py`) must pass unmodified after every task. The A/B baseline is the recorded S-r2 run, or `d9a9179` run from a separate worktree.
- **G2.** A removed `SocietyPolicy`/`ScaffoldingPolicy` field fails validation with a message that names it and says to delete it (a `mode="before"` validator, `domain._refuse_removed`, Task 5). Update `work/society-s1/run-plan.example.json`, `work/society-s1/RUN_PLAN.md` and the tests that pin the policy shape in the same task.
- **G3.** Runtime changes that alter what the model sees are opt-in config (runtime lane only). Society-lane behaviour changes are not flags.
- **G4.** Runtime reservations are the runtime lane's; this plan changes none.
- **G5.** No database migrations except Task 20's `library_notes` table. New state goes in JSON payloads. Every stored S1 record stays readable: read new keys with `.get(key, default)` and map legacy values (for example legacy node statuses read as `open`).
- **G6.** Out of scope, listed as next steps in the PR descriptions: #25 (a harder target), the paid A/B validation run (needs an explicit budget), #12d (olean-based imports), warm-REPL reuse, raising or splitting the org TPM limit.
- **G7.** Never run `uv sync`. Tests: `PYTHONPATH=src .venv/bin/python -m pytest <file> -q`. `ruff check` and `ruff format --check` on `src tests tools infra migrations` must be clean. No absolute `/Users/...` paths or usernames in anything committed. Commit with `git -c user.name=Kieran -c user.email=88352982+zubadestroyer1@users.noreply.github.com commit …`, and end the message with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Never push; never touch other worktrees or branches; never call a paid API. Docker/Colima only on the `physharness-pilot` profile, and only in Task 2 and Task 13's one real-image timing check for the `find_declaration` index builder (F13); never any other Colima profile.
- **G8.** Keep the whole suite green after every task. Update the docs that describe changed behaviour in the same task (`docs/RESEARCH_NETWORK.md`, `PLAN.md`, `docs/EXECUTION.md`, `work/society-s1/RUN_PLAN.md`, `docs/FORMAL_ENVIRONMENT.md`).
- **S1 (#1).** Run the statement checker from the uploaded workspace-relative paths, with no `/tmp` staging. Self-test it at provision in `WorkspaceTools._ensure`, cached per process per workbench image; failure is `STATEMENT_CHECK_UNAVAILABLE` (fatal). Log `statement_check_unavailable` at ERROR through the JSON logger `extra`.
- **S2 (#2).** A small tmpfs at `/etc/profile.d` in `local_docker._create_once` holds one PATH script written once per container; the image's own `/etc/profile.d` must be empty (checked on the real image). Reword the `shell` description. Verify on a real `physharness-pilot` container; if infeasible, STOP and report; never rebuild images.
- **S3 (#3).** `lean_check` defaults to `automate=false` at both declaration sites.
- **S4 (#5).** Caps say "budget, not input: limit N, used N"; workspace transfers pass the provider's reason through; `CONTEXT_EVIDENCE_KIND` names the kind and the allowed kinds; every society tool id accepts a unique 8-hex prefix through one shared resolver (`service.resolve_id`), which Task 9 reuses. `ensure_ascii=False` in `responses.py` is the runtime lane's.
- **S5 (#15).** No labs and no cross-lab ban. Messages go to one branch, or to a node's author and live claimants; rate-limited per sender (`SocietyPolicy.messages_per_minute`); referees stay unreachable. Anti-herding now comes from relevance routing, the rate limit and declared alternative routes; record this in PLAN.md and `docs/RESEARCH_NETWORK.md`.
- **S6 (#20).** Remove check-ins and stagnation nudges; keep the stagnation loop detector.
- **S7 (#18).** One society prompt view for the prompt and the compaction anchor: target, objective, constitution, live frontier and claims. The referee prompt is the review packet plus the referee constitution (and the target's six fields).
- **S8 (#13).** Refuse claims on the goal; never push a reader's own posts and advance its cursor past them; compact one-line updates with 8-hex ids; the goal thread is pull-only.
- **S9 (#12).** `lean_source` publication ranked verified, complete or partial; a node with an elaborated Lean statement and no source imports as a `sorry` stub; a platform inliner expands `import Commons.N<hex8>` in `lean_check` and `submit_for_verification`, and the verifier gets one flattened file whose provenance lists the imported nodes; a `commons_fetch` tool; provenance edges and a provenance reuse metric; one sentence saying the workspace is private.
- **S10 (#17).** Statuses `open`, `accepted`, `refuted`, `abandoned`; legacy ladder values read as `open`. No fidelity reviews and no status move but abandon and accept. Referees review plans only; a compiled node gets `REVIEW_UNNEEDED`. A verified proof accepts the nodes it imported. `record_lean_source` replaces `record_local_compile`. The metrics tool keeps reading raw S1 exports.
- **S11 (#19).** Remove `inbox`, `lean_sketch` and `load_skill`; keep `notebook`. Merge `search_library` and `read_source` into `find_declaration` (ranked `Name signature — file:line` rows, at most 20, did-you-mean; reads bounded to ±40 lines and 4,000 bytes; a bounded header-scan index cached per `environment_digest`; `#check` verifies signatures). Tool-count assertions change once, in Task 21.
- **S12 (#21).** A skeleton is a node whose published source imports stub nodes; `lean_check(stubs=true)` creates them. Optional, not a phase.
- **S13 (#23).** Every recruit brief gets a scope paragraph; the librarian hat is narrowed; `until_proved=true` ends a recruit once its node has a complete source; a joined recruit's session ends after `return_result`.
- **S14 (#14).** `wait(for="events")` wakes on a routed post or message, a watched node or branch, or a long-pole change; a minimum sleep; native resume with a short wake note; wake checks only when new events exist; the run stops when every agent waits and nothing is admissible; the long pole is shown to idle agents.
- **S15 (#16).** Admit society work while remaining dollars exceed a floor; task-count caps become an optional operator guard that ignores referees; `SocietyPolicy.referee_slots` is a pool inside `max_concurrency`.
- **S16 (#22).** Claims take an optional `route` and `time_box_minutes`; several claims per node stay allowed (distinct routes are what the frontier rewards); when one route compiles the other claimants get an urgent note; one diversity norm.
- **S17 (#24).** A project-scoped `library_notes` table keyed by `environment_digest` (migration `0004`), a `library_notes(action=read|append)` tool (notes ≤ 2,000 chars), a one-line prompt pointer, notes surfaced by `find_declaration` on weak hits, and a checked-in seed keyed by the S1 environment digest.

**Merge note.** The runtime lane (branch `society/s1-remediation-runtime`) refactors `ResponsesRuntime._loop` and edits reservation code in `research_worker.py`. Keep this lane's edits inside the functions each task names (`_receive_updates`, `_maybe_handoff`, the boundary hook, the prompt block, the runner loop) so the lanes merge cleanly. Two runtime-lane changes have a hard cross-lane constraint on this plan: the runtime lane's `recall_output` built-in tool must stay opt-in (registered only when `context_budget` is set) and out of `SOCIETY_TOOL_NAMES`, or Task 21's literal 24/23/15 tool counts break after the lanes merge; and the runtime lane's checkpoint slimming must keep `native_state["input"]` intact, because Task 17's society native wake replays it.

**Common test helpers** (already in `tests/`; reuse, do not copy): `lab` (`tests/conftest.py:10`); `society_lab`, `set_status` (`tests/commons_helpers.py`); in `tests/test_society_tools.py`: `run_worker` (`:140`), `clock` (`:211`), `FakeLean` (`:217`), `FakeWorkspace` (`:289`), `CatalogService`, `policy_dict`, `names`, `definition`, `catalog`, `widest`, `referee_catalog`, `REFEREE_TOOLS` (`:331-395`), `running` (`:398`), `profile` (`:417`), `call` (`:428`), `lemma_args` (`:432`), `PROOF`, `LEAN` (`:197-202`), `society_runner`, `run_manifest`, `scripted_society_route` (`:1531-1575`); `message`, `response`, `tool_call` (`tests/test_execution_responses.py`, `tests/test_research_loop_integration.py`); `started` (`tests/test_research_workforce.py:24`); `backend_lab` (`tests/test_commons_postgresql.py:37`); `migration_config` (`tests/test_infrastructure.py:14`).

---

## Tier 0 (one PR, base `main`)

> **As shipped (Tier 0).** The Tier-0 PR differs from the tasks below in these ways:
> - **Task 1b was added.** The checker imports only the Lean modules it uses, not `Lean`, so an `import Lean` file no longer OOMs the 2 GiB workbench. The statement check assumes a pre-warmed VM (`work/society-s1/RUN_PLAN.md`, section 8).
> - **Task 2:** the profile-write step catches `BaseException` and quarantines the container. Its real test, `test_real_login_shell_path`, checks the login-shell `PATH` and lists the raw image's `/etc/profile.d`.
> - **The final review's fixes:** the routing arguments `message.to` and `wait.ids` resolve a prefix only among their own targets; a failed checker self-test provisions no later workspace; `TASK_PENDING_CAP` is retryable.
>
> See `docs/FORMAL_ENVIRONMENT.md` (Workbench v2) and `docs/RESEARCH_NETWORK.md` for the details.

### Task 1: Statement checker runs from the workspace, self-tests at provision, alarms on failure (#1)

**Files:**
- Modify: `src/physharness/orchestration/lean_session.py:17-31` (imports, logger), `:63-68` (comment on `CHECK_FILES`), `:936-1012` (`verify_statement`)
- Modify: `src/physharness/orchestration/workspace_tools.py:1-17` (imports, constants), `:44-64` (`WorkspaceTools`: attribute, `_ensure`, new `_self_test_checker`)
- Modify: `src/physharness/orchestration/society_tools.py:515-544` (`society_tools`: enable the self-test)
- Modify: `src/physharness/orchestration/research_worker.py:67` (`FATAL_TOOL_CODES`)
- Modify: `docs/FORMAL_ENVIRONMENT.md` (the "On both images, a local compile …" paragraph, ~`:160-172`), `docs/RESEARCH_NETWORK.md:138-141`
- Test: `tests/test_statement_check.py` (plumbing section, after `:652`), `tests/test_society_tools.py`

**Interfaces:**
- Consumes: `LeanSession.verify_statement(source, header, name, signature, *, operation_id, timeout=CHECK_TIMEOUT_SECONDS) -> dict` (unchanged signature).
- Produces: `WorkspaceTools.checker_self_test: bool` (class attribute, default `False`); `workspace_tools._CHECKER_SELF_TESTS: dict[str, bool]` (template id → checker judged); `workspace_tools.CHECKER_SELF_TEST: tuple[str, str, str, str]` (source, header, name, signature); error code `STATEMENT_CHECK_UNAVAILABLE` (status 503, in `FATAL_TOOL_CODES`); log messages `statement_check_unavailable` (logger `physharness.orchestration.lean_session`) and `statement_check_self_test_failed` (logger `physharness.orchestration.workspace_tools`), both ERROR with `extra["error_code"]`.

- [ ] **Step 1: Write the failing tests** (append to the plumbing section of `tests/test_statement_check.py`; add `import logging`, `from physharness.orchestration import workspace_tools as workspace_tools_module` and `from physharness.orchestration.workspace_tools import WorkspaceTools` to its imports)

```python
async def test_statement_check_runs_from_workspace_paths_without_staging():
    ok = json.dumps({"ok": True, "axioms": [], "reason": None})
    tools = CheckTools((ok, 0))
    assert (await _verify(tools))["ok"] is True
    [script] = [text for kind, text in tools.calls if kind == "run"]
    assert "/tmp" not in script and "mkdir" not in script and "mv -f" not in script
    assert ".physharness/statement_check.py --timeout" in script
    assert "--checker .physharness/statement_check.lean" in script

async def test_statement_check_succeeds_when_tmp_is_read_only(lean_env):  # noqa: F811
    """The S1 bug: /tmp is part of the workbench's read-only root, so staging there failed."""
    shim = lean_env.root / "bin"
    (shim / "lean.py").write_text(FAKE_LEAN)
    (shim / "lake").write_text(
        f"#!/bin/sh\nshift 3\nexec {shlex.quote(sys.executable)} "
        f'{shlex.quote(str(shim / "lean.py"))} "$@"\n'
    )
    (shim / "lake").chmod(0o755)
    blocker = lean_env.root / "not-a-directory"
    blocker.write_text("")
    lean_env.runtime = blocker / "rt"  # mkdir -p under a regular file fails, like /tmp there
    verdict = await _verify(FakeWorkspaceTools(lean_env, background=False))
    assert verdict["ok"] is True and verdict["axioms"] == ["propext"]

async def test_statement_check_unavailable_is_logged_at_error(caplog):
    with caplog.at_level(logging.ERROR, logger="physharness.orchestration.lean_session"):
        verdict = await _verify(CheckTools(("", 97), ("", 97)))
    assert verdict["reason"] == "statement_check_unavailable"
    [record] = [r for r in caplog.records if r.getMessage() == "statement_check_unavailable"]
    assert record.levelname == "ERROR" and record.error_code == "statement_check_unavailable"

OK_VERDICT = {"ok": True, "reason": None, "axioms": [], "detail": None, "backend": CHECK_BACKEND}
BROKEN = {**OK_VERDICT, "ok": False, "reason": "statement_check_unavailable", "axioms": None}

@pytest.fixture
def self_tests(monkeypatch):
    cache = {}
    monkeypatch.setattr(workspace_tools_module, "_CHECKER_SELF_TESTS", cache)
    return cache

def provisioning_tools(verdict, template_id="image-a"):
    """A WorkspaceTools whose broker provisions instantly and whose checker answers `verdict`."""
    tools = WorkspaceTools.__new__(WorkspaceTools)
    tools.policy = SimpleNamespace(template_id=template_id, timeout_seconds=600, cost_bound_usd=0)
    tools.workspace, tools.cleanup_report, tools.checker_self_test = None, None, True
    provisions, checks = [], []

    async def provision(**kwargs):
        provisions.append(kwargs)
        return {"id": "ws", "execution_id": "vm"}

    async def verify_statement(source, header, name, signature, *, operation_id):
        checks.append((header, name, signature))
        return verdict

    tools.broker = SimpleNamespace(task_id="task", holder="holder", provision=provision)
    tools._lean_session = SimpleNamespace(verify_statement=verify_statement)
    return tools, provisions, checks

async def test_checker_self_test_runs_once_per_image(self_tests):
    first, _, checks = provisioning_tools(OK_VERDICT)
    second, _, later = provisioning_tools(OK_VERDICT)
    await first._ensure()
    await first._ensure()
    await second._ensure()
    assert checks == [("import Lean", "physharness_checker_self_test", ": True")]
    assert later == [] and self_tests == {"image-a": True}

async def test_unavailable_checker_fails_fast_and_logs(self_tests, caplog):
    tools, _, _ = provisioning_tools(BROKEN)
    with caplog.at_level(logging.ERROR), pytest.raises(HarnessError) as error:
        await tools._ensure()
    assert error.value.code == "STATEMENT_CHECK_UNAVAILABLE" and error.value.status == 503
    with pytest.raises(HarnessError):
        await tools._ensure()  # every later use of this workspace fails the same way
    [record] = [r for r in caplog.records if r.getMessage() == "statement_check_self_test_failed"]
    assert record.error_code == "STATEMENT_CHECK_UNAVAILABLE"
    other, _, checks = provisioning_tools(BROKEN)
    with pytest.raises(HarnessError):
        await other._ensure()
    assert checks == []  # the per-image verdict is cached for the process
```

  Also (specified): `test_checker_self_test_timeout_is_retried_and_off_by_default` — a `check_timeout` verdict provisions without raising and caches nothing (`self_tests == {}`), and with `checker_self_test = False` no check runs.

Add to `tests/test_society_tools.py` (after `test_society_catalog_without_literature_or_review`):

```python
def test_society_catalog_self_tests_the_checker_for_builders_only():
    context = {"task_id": "t", "holder": "h", "fence": 1}
    agent = SimpleNamespace(experiment_id="e", project_id="lab")
    builder, judge = FakeWorkspace(), FakeWorkspace()
    society_tools(CatalogService(policy_dict()), agent, "b", task_context=context, workspace_tools=builder)
    assignment = {"scope": "informal", "node_id": "n", "requested_by": "b0"}
    task = {"reply_to_parent_task_id": None, "hat": "referee", "review_assignment": assignment}
    society_tools(
        CatalogService(policy_dict(), task), agent, "b", task_context=context, workspace_tools=judge
    )
    assert builder.checker_self_test is True
    assert getattr(judge, "checker_self_test", False) is False
    assert "STATEMENT_CHECK_UNAVAILABLE" in research_worker.FATAL_TOOL_CODES
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_statement_check.py tests/test_society_tools.py -q -k "workspace_paths or read_only or logged_at_error or self_test or builders_only"`
Expected: FAIL (the script still stages to `/tmp`; `_CHECKER_SELF_TESTS` does not exist; the read-only test returns `statement_check_unavailable`).

- [ ] **Step 3: Run the checker from its workspace upload** (`lean_session.py`)
  - Add `import logging` and, after the imports, `log = logging.getLogger(__name__)`.
  - Replace the comment above `CHECK_FILES` with: `# The local-compile statement check: a stdlib driver and a Lean checker, uploaded to .physharness/ in the workspace and run from there (the workbench root, /tmp included, is read-only).`
  - In `verify_statement`, delete `runtime = …` and `place = …`, and build the script from the uploaded paths (`_upload_checker` is unchanged; `statement_check.py` resolves `--checker` and `WORKDIR` with `os.path.abspath` before it changes directory, so relative paths are correct):

```python
        check_timeout, run_timeout = self._timeouts(timeout)
        uploaded = [f".physharness/{file}" for file in CHECK_FILES]
        argv = [*GUEST_PYTHON, uploaded[0], "--timeout", f"{check_timeout:g}", "--cwd", LAKE_PROJECT]
        argv += ["--checker", uploaded[1], workdir, name]
        for attempt in range(2):
            tidy = f"rm -rf {workdir}; " if attempt else ""  # the driver removes it otherwise
            script = (
                f"if ! {{ test -f {uploaded[0]} && test -f {uploaded[1]}; }}; then "
                f"{tidy}rmdir .physharness 2>/dev/null; exit {_DAEMON_MISSING}; fi; "
                f"{shlex.join(argv)}"
            )
```

  - Before `return _verdict("statement_check_unavailable")` add `log.error("statement_check_unavailable", extra={"operation_id": operation_id, "error_code": "statement_check_unavailable"})`.
  - In `tests/test_statement_check.py:634` change the comment "The VM dropped /tmp" to "A VM restore dropped the uploaded checker".

- [ ] **Step 4: Self-test at provision** (`workspace_tools.py`)
  - Add `import logging`, `log = logging.getLogger(__name__)` and, below `validated_lean_imports`:

```python
# A theorem the statement checker must accept. A society task that publishes Lean runs it
# once per process and workbench image at provision (S1: the checker never ran, silently).
CHECKER_SELF_TEST = (
    "import Lean\n\ntheorem physharness_checker_self_test : True := trivial\n",
    "import Lean",
    "physharness_checker_self_test",
    ": True",
)
_CHECKER_SELF_TESTS: dict[str, bool] = {}  # template id -> the checker ran and judged

def _checker_unavailable(template_id):
    return HarnessError(
        "STATEMENT_CHECK_UNAVAILABLE",
        f"The workbench statement checker failed its self-test on {template_id}; local "
        "compiles cannot be judged.",
        status=503,
        remediation="Stop the run and inspect the workbench (ERROR log "
        "statement_check_self_test_failed); do not run a society without the checker.",
    )
```

  - In `class WorkspaceTools`, add the class attribute `checker_self_test = False  # society_tools() enables it for tasks that publish Lean`, and replace `_ensure` with:

```python
    async def _ensure(self):
        if self.workspace is None:
            self.workspace = await self.broker.provision(
                cost_bound_usd=str(self.policy.cost_bound_usd),
                operation_id=f"workspace:{self.broker.task_id}:{self.broker.holder}",
            )
            if self.checker_self_test:
                await self._self_test_checker()
        elif self.checker_self_test and _CHECKER_SELF_TESTS.get(self.policy.template_id) is False:
            raise _checker_unavailable(self.policy.template_id)
        return self.workspace

    async def _self_test_checker(self):
        image = self.policy.template_id
        passed = _CHECKER_SELF_TESTS.get(image)
        if passed is None:
            source, header, name, signature = CHECKER_SELF_TEST
            operation = f"checker-self-test:{self.broker.task_id}:{self.broker.holder}"
            verdict = await self.lean_session().verify_statement(
                source, header, name, signature, operation_id=operation
            )
            if verdict.get("reason") == "check_timeout":
                log.warning("statement_check_self_test_timeout", extra={"operation_id": operation})
                return  # judged nothing; the next provision tries again
            passed = _CHECKER_SELF_TESTS[image] = verdict.get("ok") is True
            if not passed:
                log.error(
                    "statement_check_self_test_failed",
                    extra={"operation_id": operation, "error_code": "STATEMENT_CHECK_UNAVAILABLE"},
                )
        if not passed:
            raise _checker_unavailable(image)
```

  (`self.workspace` is set before the self-test, so the test's own `write`/`run` calls reuse it and cannot recurse.)
- [ ] **Step 5: Enable it for builders and make it fatal**
  - `society_tools.py`, right after the `lean()` helper: `if workspace_tools is not None and not referee: workspace_tools.checker_self_test = True  # publishing Lean needs the checker (S1 #1)`.
  - `research_worker.py:67`: add `"STATEMENT_CHECK_UNAVAILABLE"` to `FATAL_TOOL_CODES`.
  - `tests/conftest.py`: an autouse fixture gives every test a fresh cache (`monkeypatch.setattr("physharness.orchestration.workspace_tools._CHECKER_SELF_TESTS", {})`). `tests/test_society_tools.py::test_worker_society_profile_drives_real_workspace_tools` drives a real `WorkspaceTools` over a `FakeVM` that runs no Lean: pre-seed `{"qualified-template": True}` there so its `calls == ["create", "run", "close"]` still holds. Pre-seed the same way in any other society test that drives a real `WorkspaceTools` against a fake VM.
- [ ] **Step 6: Docs.** `docs/FORMAL_ENVIRONMENT.md`: in the local-compile paragraph add "The checker runs from its upload in the workspace (`.physharness/`); the workbench root, `/tmp` included, is read-only. A society task self-tests it once per process and image when it first provisions a workspace, and a failed self-test stops the task with `STATEMENT_CHECK_UNAVAILABLE`. The uploaded checker now lives under `/work/.physharness`, so (unlike its old `/tmp` staging) it persists into checkpoints and handoff archives. A workspace a handoff restores is already provisioned before `society_tools()` sets `checker_self_test`, so its self-test is skipped for that workspace's lifetime; this is accepted (rare, and the checker it inherited was already self-tested once)." `docs/RESEARCH_NETWORK.md:138-141`: add the same self-test sentence after "any failure to run it records nothing".
- [ ] **Step 7: Run the tests**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_statement_check.py tests/test_lean_session.py tests/test_society_tools.py tests/test_worker_vm_tools.py -q`
Expected: PASS (the real-Lean tests skip without a toolchain).

- [ ] **Step 8: Commit**

```bash
git add src/physharness/orchestration/lean_session.py src/physharness/orchestration/workspace_tools.py src/physharness/orchestration/society_tools.py src/physharness/orchestration/research_worker.py docs/FORMAL_ENVIRONMENT.md docs/RESEARCH_NETWORK.md tests/test_statement_check.py tests/test_society_tools.py
git -c user.name=Kieran -c user.email=88352982+zubadestroyer1@users.noreply.github.com commit -m "fix: run the statement checker from the workspace and self-test it at provision" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: `lake` and `lean` on the PATH in login shells (#2)

**Files:**
- Modify: `src/physharness/execution/local_docker.py:20-25` (constants), `:556-594` (`_create_once` run argv), `:606-620` (write the profile script after the identity check)
- Modify: `src/physharness/orchestration/society_tools.py:572-574` (`shell` description)
- Modify: `docs/FORMAL_ENVIRONMENT.md` ("Workbench v2" section, `:142-160`)
- Test: `tests/test_local_docker_workbench.py:45-92` and a new test; `tests/test_real_workbench_qualification.py` (two opt-in tests)

**Interfaces:**
- Consumes: `GUEST_PYTHON` (`execution/types.py:28`), `LeanSession` (Task 1).
- Produces: `local_docker.PROFILE_D_TMPFS: str`, `local_docker.PROFILE_SCRIPT_PATH = "/etc/profile.d/physharness-path.sh"`, `local_docker._PROFILE_WRITER: str`.

- [ ] **Step 1: Write the failing tests.** In `tests/test_local_docker_workbench.py` import `import subprocess`, `from physharness.execution import local_docker`, `from physharness.execution.types import GUEST_PYTHON`, then add to `test_container_launch_isolation_and_command_budgets` after the `required` loop:

```python
    tmpfs = [run[index + 1] for index, token in enumerate(run) if token == "--tmpfs"]
    assert tmpfs[0].startswith("/work:") and tmpfs[1] == local_docker.PROFILE_D_TMPFS
    writes = [
        (index, argv)
        for index, (argv, *_) in enumerate(transport.commands)
        if local_docker._PROFILE_WRITER in argv
    ]
    [(position, write)] = writes
    assert write[3:] == ["exec", "container-id", *GUEST_PYTHON, "-c", local_docker._PROFILE_WRITER]
    assert position > next(i for i, (argv, *_) in enumerate(transport.commands) if "run" in argv)
```

and new tests:

```python
@pytest.mark.asyncio
async def test_profile_write_failure_quarantines_the_container():
    class FailingProfile(DockerTranscript):
        async def __call__(self, argv, **kwargs):
            if local_docker._PROFILE_WRITER in argv:
                self.commands.append((argv, b"", 30, 65536))
                return (1, b"", b"read-only file system")
            return await super().__call__(argv, **kwargs)

    transport = FailingProfile()
    provider = LocalDockerWorkspaceProvider(
        docker_host="unix:///tmp/physharness-pilot/docker.sock",
        image_digest="sha256:" + "a" * 64,
        timeout_seconds=120,
        runner=transport,
    )
    with pytest.raises(ExecutionError) as error:
        await provider.create()
    assert error.value.code == "PROVIDER_FAILED" and provider._quarantined is True
    assert any("rm" in argv for argv, *_ in transport.commands)

def test_profile_writer_restores_the_image_path(tmp_path, monkeypatch):
    target = tmp_path / "physharness-path.sh"
    monkeypatch.setenv("PATH", "/opt/lean/bin:/usr/local/bin:/usr/bin:/bin")
    exec(  # noqa: S102 - the harness's own script, run as the guest would run it
        local_docker._PROFILE_WRITER,
        {"__builtins__": __builtins__, "open": lambda path, mode: open(target, mode)},
    )
    assert target.read_text() == "export PATH=/opt/lean/bin:/usr/local/bin:/usr/bin:/bin\n"
    sourced = subprocess.run(
        ["/bin/sh", "-c", f'PATH=/bin; . "{target}"; printf %s "$PATH"'],
        capture_output=True, text=True, check=True,
    )
    assert sourced.stdout == "/opt/lean/bin:/usr/local/bin:/usr/bin:/bin"
```

In `tests/test_real_workbench_qualification.py` add (imports: `from pathlib import Path`, `from types import SimpleNamespace`, `from physharness.orchestration.lean_session import LeanSession`):

```python
@pytest.mark.integration
async def test_real_login_shell_path_and_statement_check():
    host = os.environ.get("PHYSHARNESS_WORKBENCH_DOCKER_HOST")
    image = os.environ.get("PHYSHARNESS_WORKBENCH_IMAGE_DIGEST")
    if not host or not image:
        pytest.skip("Dedicated workbench endpoint and image digest are required")
    provider = LocalDockerWorkspaceProvider(docker_host=host, image_digest=image, timeout_seconds=180)

    async def run(arguments, operation_id):
        request = CommandRequest(operation_id=operation_id, max_output_bytes=65536, **arguments)
        return (await provider.run(request)).model_dump()

    async def write(arguments, operation_id):
        data = arguments["content"].encode()
        await provider.upload_file(arguments["path"], data, expected_execution_id=provider.execution_id)
        return {"path": arguments["path"]}

    tools = SimpleNamespace(policy=SimpleNamespace(timeout_seconds=170), run=run, write=write,
                            allows_background_processes=lambda: False)
    try:
        await provider.create()
        login = await run({"argv": ["bash", "-lc", "command -v lake && command -v lean"],
                           "cwd": ".", "timeout_seconds": 30}, "login-path")
        assert login["exit_code"] == 0, login["stderr"]
        assert [Path(line).name for line in login["stdout"].split()] == ["lake", "lean"]
        listed = await run({"argv": ["ls", "-A", "/etc/profile.d"], "cwd": ".", "timeout_seconds": 30}, "ls")
        assert listed["stdout"].split() == ["physharness-path.sh"]
        verdict = await LeanSession(tools).verify_statement(  # Task 1's checker, on the real image
            "import Lean\n\ntheorem physharness_checker_self_test : True := trivial\n",
            "import Lean", "physharness_checker_self_test", ": True", operation_id="real-self-test",
        )
        assert verdict["ok"] is True, verdict
    finally:
        await provider.close()
```

- [ ] **Step 2: Run the unit tests to verify they fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_local_docker_workbench.py -q`
Expected: FAIL (`PROFILE_D_TMPFS` is undefined).

- [ ] **Step 3: Implement** (`local_docker.py`)
  - Below `_IMAGE`:

```python
# Login shells (bash -l) source /etc/profile, which resets PATH on Debian and drops the
# image's /opt/lean/bin (S1: `bash -lc 'lake …'` failed 37 of 38 times). A small tmpfs at
# /etc/profile.d holds one script that restores the image's own PATH. The image ships no
# files there; the opt-in real-image test checks it.
PROFILE_D_TMPFS = "/etc/profile.d:rw,noexec,nosuid,nodev,size=65536,mode=0755,uid=65532,gid=65532"
PROFILE_SCRIPT_PATH = "/etc/profile.d/physharness-path.sh"
_PROFILE_WRITER = (
    "import os, shlex\n"
    f"with open({PROFILE_SCRIPT_PATH!r}, 'x') as out:\n"
    "    out.write('export PATH=' + shlex.quote(os.environ['PATH']) + '\\n')\n"
)
```

  - In `_create_once`'s `run` argv, after the `/work` tmpfs pair, add `"--tmpfs", PROFILE_D_TMPFS,`.
  - After the container-identity check (just before the final `return self`):

```python
        try:
            # docker exec without -e runs with the image's Config.Env PATH.
            await self._call(
                ["exec", self._container_id, *GUEST_PYTHON, "-c", _PROFILE_WRITER], timeout=30
            )
        except ExecutionError:
            self._quarantined = True
            try:
                await self._call(["rm", "-f", self._planned_name], timeout=30)
            except ExecutionError:
                pass
            raise
```

  - `society_tools.py` `shell` description becomes: `"Run a command in the offline workspace VM (python3, lake, lean, ...). Pass argv directly (['lake', 'env', 'lean', '/work/F.lean']) or through bash -c; login shells work too. For Lean use cwd='/opt/sources/physlib' and pass files by their /work paths. Exit status and output are evidence, never proof acceptance."`
- [ ] **Step 4: Run the unit tests**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_local_docker_workbench.py tests/test_workbench_failure_classification.py tests/test_worker_predispatch_rejection.py tests/test_workspace_cleanup_authority.py tests/test_society_tools.py -q`
Expected: PASS. A test whose scripted runner answers every `exec` in order may need its expected sequence extended by the one profile write; change only that expectation.

- [ ] **Step 5: Verify on a real container (the `physharness-pilot` profile only).** Run from this worktree:

```bash
unset COLIMA_HOME
colima list                                   # note whether physharness-pilot is Running or Stopped
colima start --profile physharness-pilot      # only if it was Stopped
export DOCKER_HOST="unix://$HOME/.colima/physharness-pilot/docker.sock"
export IMAGE=sha256:1830c99e8c5abc0ade48d98860d541f7f50eb6f1cdfefde2395315e1290debc5
docker --host "$DOCKER_HOST" image inspect --format '{{.Id}}' "$IMAGE"          # prints $IMAGE
# (a) the image's own /etc/profile.d must list nothing:
docker --host "$DOCKER_HOST" run --rm --network none --read-only --user 65532:65532 \
  --entrypoint /bin/sh "$IMAGE" -c 'ls -A /etc/profile.d 2>/dev/null; echo "listed=$?"'
# (b) the bug reproduces without the fix (expect a failing lake lookup):
docker --host "$DOCKER_HOST" run --rm --network none --read-only --user 65532:65532 \
  --entrypoint /bin/bash "$IMAGE" -lc 'command -v lake; echo "lake=$?"'
# (c) the fix and Task 1's checker, through the provider:
PHYSHARNESS_WORKBENCH_DOCKER_HOST="$DOCKER_HOST" PHYSHARNESS_WORKBENCH_IMAGE_DIGEST="$IMAGE" \
  PYTHONPATH=src .venv/bin/python -m pytest tests/test_real_workbench_qualification.py -q
docker --host "$DOCKER_HOST" ps --all --filter label=physharness.workbench=true --format '{{.Names}}'  # empty
colima stop --profile physharness-pilot       # only if it was Stopped before this step
```

  **STOP and report (do not commit the `local_docker.py` change, do not rebuild any image)** if (a) lists any file, if a container with the `/etc/profile.d` tmpfs fails to start, or if the new real test fails. Put the outputs of (a), (b) and (c) in the task report. If (b) already finds `lake`, report it and continue.

  This is also the one other place Docker/Colima runs (G7): Task 13, once its `find_declaration` index builder exists, reuses this same `physharness-pilot` container protocol once more to time that script against the real Mathlib/Physlib trees (F13); nothing here needs to anticipate that.
- [ ] **Step 6: Docs.** `docs/FORMAL_ENVIRONMENT.md`, Workbench v2: "Each workbench container mounts a 64 KiB tmpfs at `/etc/profile.d` holding `physharness-path.sh`, which restores the image's `PATH` for login shells (`bash -lc`). The image ships no files there; `tests/test_real_workbench_qualification.py` checks this and a login-shell `lake` lookup on a real container."
- [ ] **Step 7: Commit**

```bash
git add src/physharness/execution/local_docker.py src/physharness/orchestration/society_tools.py docs/FORMAL_ENVIRONMENT.md tests/test_local_docker_workbench.py tests/test_real_workbench_qualification.py
git -c user.name=Kieran -c user.email=88352982+zubadestroyer1@users.noreply.github.com commit -m "fix: restore the image PATH for login shells in the workbench" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Automation off by default, and errors that say what happened (#3, #5a, #5b, #5c)

**Files:**
- Modify: `src/physharness/orchestration/society_tools.py:699-731` (both `lean_check` declarations)
- Modify: `src/physharness/workforce.py:23-31` (helper), `:309-312` (cap raises)
- Modify: `src/physharness/orchestration/workspaces.py:983-990` (refusal message)
- Modify: `src/physharness/memory.py:24-42` (constant), `:107-116` (`_reference`), `:219-220` (`history_page`), `:255-256` (`read_record`)
- Modify: `PLAN.md:172` (automation on failure)
- Test: `tests/test_society_tools.py`, `tests/test_research_workforce.py`, `tests/test_workspace_service.py:462-485`, `tests/test_memory.py:300-317`

**Interfaces:**
- Produces: `workforce._cap_reached(code: str, what: str, limit: int, used: int) -> HarnessError` with `details == {"limit": limit, "used": used}`; `memory.ALLOWED_KINDS_TEXT = "artifact, claim, program, source, task, verification"`; `CONTEXT_EVIDENCE_KIND` errors carry `details["kind"]` and `details["allowed"]` (sorted list).

- [ ] **Step 1: Write the failing tests**

`tests/test_society_tools.py`:

```python
async def test_lean_check_automation_is_off_by_default(lab):
    service, author, exp, branches, (alpha, beta) = society_lab(lab)
    agent, context = running(service, author, exp, alpha.branch_id)
    workspace = FakeWorkspace()
    tools = profile(service, agent, context, workspace=workspace)
    created = await call(tools, "commons_node", lemma_args())
    await call(tools, "lean_check", {"source": PROOF})
    assert workspace.lean.calls == [("check", False)]
    requested = service.request_review(created["id"], "informal", beta, "review")
    task = service.get_record("task", requested["review_task_id"], author)
    judge, judge_context = running(service, author, exp, requested["branch_id"], task=task)
    judge_space = FakeWorkspace()
    await call(profile(service, judge, judge_context, workspace=judge_space), "lean_check", {"source": PROOF})
    assert judge_space.lean.calls == [("check", False)]
```

`tests/test_research_workforce.py`:

```python
def test_task_caps_report_budget_not_input(lab):
    service, researcher, operator, experiment = started(lab)
    service.configure_workforce(
        experiment["id"], ConfigureWorkforceRequest(max_total_tasks=3, max_pending_tasks=1),
        operator, "configure",
    )
    roots = SeedPortfolioRequest(roots=[PortfolioRoot(title="A", objective="Try A")])
    branch = service.seed_portfolio(experiment["id"], roots, operator, "seed")["roots"][0]["branch"]
    with pytest.raises(HarnessError) as pending:
        service.create_task(TaskCreate(branch_id=branch["id"], objective="Two"), researcher, "two")
    cap = pending.value
    assert cap.code == "TASK_PENDING_CAP" and cap.details == {"limit": 1, "used": 1}
    assert "budget, not input: limit 1, used 1" in cap.message
    assert cap.remediation.startswith("This is a budget limit, not an input error.")
```

`tests/test_workspace_service.py`, inside the loop of `test_definite_transfer_refusal_is_replayed_without_quarantine`: `assert error.value.message == "definite helper refusal; VM is available."`

`tests/test_memory.py`, after the existing `CONTEXT_EVIDENCE_KIND` assertion (`:317`):

```python
    assert exc.value.message == (
        "A branch record is not portable evidence; cite one of: "
        "artifact, claim, program, source, task, verification."
    )
    assert exc.value.details == {"kind": "branch", "allowed": sorted(HISTORY_KINDS)}
    for read in (
        lambda: memory.history_page(alpha.branch_id, alpha, kind="commons_node"),
        lambda: memory.read_record(alpha.branch_id, alpha, kind="commons_node", identifier="x"),
    ):
        with pytest.raises(HarnessError) as kind:
            read()
        assert kind.value.message.startswith("'commons_node' is not a portable record kind")
        assert kind.value.details["kind"] == "commons_node"
```

(import `HISTORY_KINDS` from `physharness.memory`).

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_society_tools.py tests/test_research_workforce.py tests/test_workspace_service.py tests/test_memory.py -q`
Expected: FAIL in exactly the new and extended tests (automation `True`; generic messages).

- [ ] **Step 3: Implement**
  - `society_tools.py:706` and `:730`: `defaults={"automate": False}` and `defaults={"node_id": None, "automate": False}`. In both descriptions replace "automation on holes (automate=true)" with "automation on holes (automate=true; off by default, since automation can exhaust the workbench's memory)".
  - `workforce.py`, below `DEFAULT_MAX_PENDING_TASKS`:

```python
def _cap_reached(code, what, limit, used):
    """A task-count cap is a budget the operator set, never a malformed request (S1 F6)."""
    wait = ", or retry after a queued or running task ends" if code == "TASK_PENDING_CAP" else ""
    return HarnessError(
        code,
        f"Experiment {what} cap reached (budget, not input: limit {limit}, used {used}).",
        remediation="This is a budget limit, not an input error. Do not retry the same "
        f"request; continue with work already running{wait}.",
        details={"limit": limit, "used": used},
    )
```

    and the raises become `raise _cap_reached("TASK_TOTAL_CAP", "task total", total_limit, total)` and `raise _cap_reached("TASK_PENDING_CAP", "pending task", pending_limit, pending)`.
  - `workspaces.py:983-990`: the failure message is always `f"{exc}; VM is available."` (delete the `WORKSPACE_TRANSFER_REJECTED` special case; every raise site's text is harness-authored).
  - `memory.py`: below `HISTORY_KINDS` add `ALLOWED_KINDS_TEXT = ", ".join(sorted(HISTORY_KINDS))`. In `_reference` split the check:

```python
        if row.kind not in HISTORY_KINDS:
            raise _error(
                "CONTEXT_EVIDENCE_KIND",
                f"A {row.kind} record is not portable evidence; cite one of: {ALLOWED_KINDS_TEXT}.",
                kind=row.kind,
                allowed=sorted(HISTORY_KINDS),
            )
        artifact_kind = row.payload.get("artifact_kind")
        if row.kind == "artifact" and artifact_kind in self.service._private_artifact_kinds:
            raise _error(
                "CONTEXT_EVIDENCE_KIND",
                f"A {artifact_kind} artifact is private platform state, not portable evidence; "
                f"cite one of: {ALLOWED_KINDS_TEXT}.",
                kind="artifact",
                artifact_kind=artifact_kind,
                allowed=sorted(HISTORY_KINDS),
            )
```

    and in `history_page` and `read_record`: `raise _error("CONTEXT_EVIDENCE_KIND", f"{kind!r} is not a portable record kind; use one of: {ALLOWED_KINDS_TEXT}.", kind=kind, allowed=sorted(HISTORY_KINDS))`.
  - `PLAN.md:172`: "On failure, the check can run automation … (`automate=true`; off by default since S1, where it exhausted the 2 GiB workbench 14 of 14 times) …".
- [ ] **Step 4: Run the tests**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_society_tools.py tests/test_research_workforce.py tests/test_workspace_service.py tests/test_memory.py tests/test_commons_review.py tests/test_workspace_cleanup_authority.py tests/test_workbench_failure_classification.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/physharness/orchestration/society_tools.py src/physharness/workforce.py src/physharness/orchestration/workspaces.py src/physharness/memory.py PLAN.md tests/test_society_tools.py tests/test_research_workforce.py tests/test_workspace_service.py tests/test_memory.py
git -c user.name=Kieran -c user.email=88352982+zubadestroyer1@users.noreply.github.com commit -m "fix: default lean_check automation off and make cap, transfer and evidence errors specific" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: One shared resolver for 8-hex id prefixes (#5d)

**Files:**
- Modify: `src/physharness/service.py:1-30` (import `re`), `:502-517` (constants and three methods after `get_record`)
- Modify: `src/physharness/orchestration/society_tools.py:192-262` (`ident`, `_split`, `_check_caps`, `_resolved`, `_guard`), `:532-536` (`add`), and every id-typed property: `:713`, `:869`, `:999-1001`, `:1033`, `:1096`, `:1113`, `:1121`, `:1123`, `:1177-1179`, `:1189`, `:1272`, `:1313`, `:1315`, `:1338`, `:1394`, `:1437`, `:1466`
- Modify: `docs/RESEARCH_NETWORK.md` (society section, a new "Ids" bullet)
- Test: create `tests/test_id_prefixes.py`

**Interfaces:**
- Produces: `service.ID_PREFIX` (compiled `[0-9a-f]{8}[0-9a-f-]{0,27}`), `service.MAX_PREFIX_CANDIDATES = 20`; `HarnessService._prefix_candidates(session, prefix: str, actor: Principal, kinds: tuple[str, ...]) -> list[RecordRow]`; `HarnessService._resolve_prefix(session, identifier, actor, kinds) -> str`; `HarnessService.resolve_id(identifier, actor, kinds) -> str`; error `AMBIGUOUS_ID` (409, `details["candidates"] == [{"id", "kind"}]`). In `society_tools.py`: `ident(description: str, kinds: tuple[str, ...], *, nullable=False) -> dict` and `EVIDENCE_KINDS`. Tasks 6, 9, 11 and 16 declare their id properties with `ident` (Task 20's `library_notes` tool has no id-typed property).

- [ ] **Step 1: Write the failing tests** (`tests/test_id_prefixes.py`)

```python
"""Tier-0 #5d: model-supplied ids accept a unique prefix of at least 8 hex characters."""

import pytest
from commons_helpers import society_lab
from test_society_tools import call, lemma_args, profile, running

from physharness.commons_models import NodeCreate
from physharness.errors import HarnessError
from physharness.storage import RecordRow

NODE = ("commons_node",)

def node_with_id(service, experiment, agent, identifier, title):
    with service.db.transaction() as session:
        row = session.get(RecordRow, experiment["id"])
        payload = service._node_payload(
            row, node_type="lemma", title=title, statement=title,
            status="open", status_reason="test",
        )
        return service._insert(
            session, "commons_node", agent, {**payload, "branch_id": agent.branch_id},
            record_id=identifier,
        )

def test_unique_prefix_resolves_and_anything_else_passes_through(lab):
    service, _, exp, _, (alpha, _) = society_lab(lab)
    node = service.create_node(
        exp["id"], NodeCreate(node_type="lemma", title="L", statement="L holds."), alpha, "node"
    )
    for prefix in (node["id"][:8], node["id"][:13], node["id"]):
        assert service.resolve_id(prefix, alpha, NODE) == node["id"]
    assert service.resolve_id(node["id"][:7], alpha, NODE) == node["id"][:7]
    assert service.resolve_id(node["id"][:8], alpha, ("branch",)) == node["id"][:8]
    assert service.resolve_id("0" * 8, alpha, NODE) == "0" * 8
    _, _, other, _, (gamma, _) = society_lab(lab, prefix="other")
    hidden = service.create_node(
        other["id"], NodeCreate(node_type="lemma", title="H", statement="H holds."), gamma, "h"
    )
    assert service.resolve_id(hidden["id"][:8], alpha, NODE) == hidden["id"][:8]

def test_ambiguous_prefix_lists_the_candidates(lab):
    service, _, exp, _, (alpha, _) = society_lab(lab)
    first = node_with_id(service, exp, alpha, "abcdef12-0000-4000-8000-000000000001", "A")
    second = node_with_id(service, exp, alpha, "abcdef12-0000-4000-8000-000000000002", "B")
    with pytest.raises(HarnessError) as error:
        service.resolve_id("abcdef12", alpha, NODE)
    assert error.value.code == "AMBIGUOUS_ID"
    assert [c["id"] for c in error.value.details["candidates"]] == [first["id"], second["id"]]

async def test_society_tools_accept_prefixes_for_id_arguments(lab):
    service, author, exp, _, (alpha, _) = society_lab(lab)
    agent, context = running(service, author, exp, alpha.branch_id)
    tools = profile(service, agent, context)
    created = await call(tools, "commons_node", lemma_args())
    short = created["id"][:8]
    assert (await call(tools, "commons_read", {"node_id": short}))["node"]["id"] == created["id"]
    assert (await call(tools, "commons_claim", {"node_id": short, "action": "claim"}))[
        "node_id"
    ] == created["id"]
    posted = await call(
        tools, "commons_post", {"node_id": short, "kind": "finding", "abstract": "A finding."}
    )
    assert posted["node_id"] == created["id"]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_id_prefixes.py -q`
Expected: FAIL (`HarnessService` has no `resolve_id`; the tool calls return `NOT_FOUND`).

- [ ] **Step 3: The resolver** (`service.py`, after `get_record`; `ID_PREFIX` and `MAX_PREFIX_CANDIDATES` at module level near `MICRO_USD`)

```python
ID_PREFIX = re.compile(r"[0-9a-f]{8}[0-9a-f-]{0,27}")
MAX_PREFIX_CANDIDATES = 20

    def _prefix_candidates(self, session, prefix, actor, kinds):
        """Visible records of ``kinds`` in the actor's experiment whose id begins with
        ``prefix``, ordered by id. Uses records_project_kind_experiment_keyset."""
        rows = session.scalars(
            select(RecordRow)
            .where(
                RecordRow.project_id == actor.project_id,
                RecordRow.kind.in_(kinds),
                record_json_text("experiment_id") == actor.experiment_id,
                RecordRow.id.startswith(prefix, autoescape=True),
            )
            .order_by(RecordRow.id)
            .limit(MAX_PREFIX_CANDIDATES + 1)
        ).all()
        return [row for row in rows if self._in_scope(session, row, actor)]

    def _resolve_prefix(self, session, identifier, actor, kinds):
        if (
            not isinstance(identifier, str)
            or len(identifier) >= 36
            or not ID_PREFIX.fullmatch(identifier)
            or not actor.experiment_id
        ):
            return identifier
        candidates = self._prefix_candidates(session, identifier, actor, kinds)
        if len(candidates) > 1:
            raise HarnessError(
                "AMBIGUOUS_ID",
                f"{len(candidates)} records begin with {identifier}; give more characters.",
                status=409,
                details={
                    "candidates": [
                        {"id": row.id, "kind": row.kind}
                        for row in candidates[:MAX_PREFIX_CANDIDATES]
                    ]
                },
                remediation="Repeat the call with a longer prefix or a full id from "
                "details.candidates.",
            )
        # Unknown ids pass through, so the caller's lookup still answers NOT_FOUND.
        return candidates[0].id if candidates else identifier

    def resolve_id(self, identifier, actor, kinds):
        """The one resolver for model-supplied ids: a full id, or a unique prefix of at least
        8 hex characters of a visible record of ``kinds`` in the actor's experiment."""
        if not isinstance(identifier, str) or not ID_PREFIX.fullmatch(identifier):
            return identifier
        with self.db.sessions() as session:
            return self._resolve_prefix(session, identifier, actor, kinds)
```

- [ ] **Step 4: Resolve at the society tool boundary** (`society_tools.py`)
  - After `text(...)`:

```python
def ident(description, kinds, *, nullable=False):
    """An id property: a full id, or a unique prefix of at least 8 hex characters (S1 #5d)."""
    schema = text(ID, f"{description} A unique 8+ hex character prefix works too.", nullable=nullable)
    return {**schema, "_id": tuple(kinds)}

EVIDENCE_KINDS = (
    "artifact", "claim", "task", "verification", "source", "program",
    "commons_node", "discussion_post", "message", "branch",
)
```

  - `_split`: after the `_cap` pop, `kinds = schema.pop("_id", None)` and `if kinds is not None: caps.append((path, "id", kinds))`. `_check_caps`: skip entries whose kind is `"id"`.
  - Add `_resolved`:

```python
def _resolved(value, path, resolve, kinds):
    if not path:
        return resolve(value, kinds) if isinstance(value, str) else value
    if path[0] == "[]":
        if not isinstance(value, list):
            return value
        return [_resolved(item, path[1:], resolve, kinds) for item in value]
    if isinstance(value, dict) and path[0] in value:
        return {**value, path[0]: _resolved(value[path[0]], path[1:], resolve, kinds)}
    return value
```
  - `_guard(handler, caps, resolve=None)`: after `_check_caps`, when `resolve` is given, apply `arguments = _resolved(arguments, path, resolve, kinds)` for every `(path, "id", kinds)` entry, then call the handler as today.
  - In `add()`: `_guard(handler, caps, lambda value, kinds: service.resolve_id(value, agent, kinds))`.
  - Replace `text(ID, …)` with `ident(…, kinds)` (same description text) at: `lean_check.node_id`, `lean_sketch.parent_node_id`, `commons_node.node_id`, `commons_node.edges[].target_id`, `commons_node.target_id`, `commons_post.node_id`, `commons_post.cites[]`, `commons_claim.node_id`, `recruit.focus_node_id`, `commons_read.node_id` → `("commons_node",)`; `commons_read.post_id`, `commons_post.reply_to_post_id` → `("discussion_post",)`; `commons_read.message_id` → `("message",)`; `read_artifact.artifact_id` and every `artifact_ids[]` item → `("artifact",)`; `message.to` → `("branch",)`; `wait.ids[]` → `("task", "branch")`; `verification_status.receipt_id` → `("verification",)`; `notebook.evidence_ids[]` → `EVIDENCE_KINDS`. Leave `commons_query.after` (a cursor) and `inbox.ack_delivery_id` as `text`.
- [ ] **Step 5: Docs.** `docs/RESEARCH_NETWORK.md`, society section, new bullet: "**Ids.** Every society tool id argument accepts the full id or a unique prefix of at least 8 hex characters of a record the agent can see; an ambiguous prefix returns `AMBIGUOUS_ID` with the candidates."
- [ ] **Step 6: Run the tests**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_id_prefixes.py tests/test_society_tools.py tests/test_commons.py tests/test_commons_discourse.py tests/test_society_simulation.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/physharness/service.py src/physharness/orchestration/society_tools.py docs/RESEARCH_NETWORK.md tests/test_id_prefixes.py
git -c user.name=Kieran -c user.email=88352982+zubadestroyer1@users.noreply.github.com commit -m "feat: accept unique 8-hex id prefixes in every society tool" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

**━━━━━━━━━━ PR BOUNDARY: Tasks 1–4 are the Tier-0 PR (base `main`). Tasks 5–21 are the society PR, stacked on it. ━━━━━━━━━━**

Before opening the Tier-0 PR: run the full suite and ruff (Task 21, Steps 4–5), and put in the PR body the G6 next steps and the real-container outputs from Task 2 Step 5.

---

## Society lane (one PR, stacked on Tier 0)

> **Merge audit (2026-09-27): the lemma store's trust boundary.** The PR 37 review found these, fixed before merge:
> - **Publication gate.** A published module's compile-time code ran in every importer's and referee's VM. `refused_command` now refuses code-running and syntax-extending commands and attributes, non-`local` notation, `unsafe` outside brackets (aesop's `unsafe` phase inside them is fine, re-audit), `#` commands that evaluate or run code (a denylist), options outside a small allow-list, and names rooted in `Lean`/`IO`, in `lean_check`, `record_lean_source`, `set_lean_statement` (a statement becomes a stub) and at inline and fetch time for records stored before the gate.
> - **Ranks rest on a judging check.** A statement check that could not judge (timeout, failed or missing checker) ranked a stated node `complete` on the file's own `#print axioms` report, which took it off the frontier and made it review-immune. Such a check now leaves the file `partial` (the result names `statement_check`); only a node with no Lean statement ranks `complete` on its own report.
> - **Ranks are transitive.** A verified importer stayed verified and off the frontier after a dependency was replaced. Publication now records the check's `closure` (each inlined module's digest), and a source whose closure no longer matches reads `stale` (`Closures`, memoized per call; direct imports recursively for records without one). A restated import stales only its own source. A complete source of an elaborated statement, like a verified one, now answers at its rank only to its publisher and the node's author, so no branch churns importers stale; on a node without one (a definition), which nothing can outrank, any branch still replaces a complete source at its rank (re-audit), trading possible churn for no permanent lock.
> - **`in_verified_proof` means imported, not used.** It credits every module the verified proof inlined, and so do the accepted-proof metrics; the field keeps its name (stored records stay readable), and the docs and the A/B metric "cross-branch imports in the accepted proof" now say it is an upper bound on reuse.
> - **Gate false refusals (re-audit).** The `#` list is now a denylist of commands that evaluate or run terms or commands (`#eval`, `#guard*`, `#reduce`, `#time`, …, matched as Lean's longest token), so Mathlib's `#s` card notation passes; a name is refused only when rooted in `Lean`/`IO`/`EIO`/`BaseIO`, the backstop; `push_neg.use_distrib`, `simprocs`, `tactic.hygienic` and `backward.*` may be set; each refusal names its workaround (`scoped` notation: write it `local`; `trace.*`: drop it).
> - **A timed-out statement check says what to do.** The check recompiles the file cold within at most 240 s, so a near-budget proof stays `partial` on every retry: a `check_timeout` (or an oversized file) now comes with a remediation to speed the proof up or split it, not to check again.
> - **Referee withholding.** With modules inlined, a message or goal with no line on the referee's own text now reaches it fenced as author data (it may be a module's output), and axiom names other than the standard three and `sorryAx` are replaced by a placeholder in the referee's own declarations' axiom lists.
> - **The goal has no module.** `commons_fetch` refused the goal, but an `import` of its module inlined a `sorry` stub of the target once it had an elaborated statement; `_module` now refuses it for both.

### Task 5: Remove check-ins and stagnation nudges; the removed-field refusal (#20)

**Files:**
- Modify: `src/physharness/domain.py:40-42` (add `_refuse_removed` after `StrictModel`), `:108-112` (`ScaffoldingPolicy`)
- Modify: `src/physharness/orchestration/society_prompt.py:25-31` (`BOUNDARIES`), delete `:104-147` (`checkin_note`, `referee_checkin_note`, `stagnation_suggestions`, `referee_stagnation_suggestions`)
- Modify: `src/physharness/orchestration/research_worker.py:54-61` (imports), delete `:1728-1748` (turn-note and suggestion wiring)
- Modify: `work/society-s1/run-plan.example.json:95-100`, `work/society-s1/RUN_PLAN.md` (any mention of check-ins or nudges as S2 settings), `PLAN.md` §3.7 (`:188-217`: the "Progress check-ins" and "Stagnation nudges" bullets), `docs/RESEARCH_NETWORK.md` ("Optional check-ins and stagnation nudges are switched per campaign.")
- Test: `tests/test_society_scaffolding.py:25-33,64-78,155-202`, `tests/test_society_tools.py:47-54,1292-1400`

**Interfaces:**
- Produces: `domain._refuse_removed(data: Any, removed: dict[str, str], model: str) -> Any` (a `mode="before"` helper Tasks 6 and 13 reuse); `domain.REMOVED_SCAFFOLDING_FIELDS: dict[str, str]`. `ResponsesRuntime`'s generic `turn_note` and `stagnation_suggestions` parameters stay (execution-layer API with their own tests); the society worker no longer passes them.

- [ ] **Step 1: Write the failing tests**

`tests/test_society_scaffolding.py` (import `ScaffoldingPolicy` from `physharness.domain` and `ValidationError` from `pydantic`):

```python
@pytest.mark.parametrize("field", ["checkin_every_turns", "stagnation_nudges"])
def test_scaffolding_policy_names_removed_fields(field):
    with pytest.raises(ValidationError) as error:
        ScaffoldingPolicy.model_validate({field: None})
    message = str(error.value)
    assert f"ScaffoldingPolicy.{field} was removed" in message
    assert "Delete it from the plan." in message
```

`tests/test_society_tools.py`:

```python
async def test_society_worker_passes_no_check_in_or_nudge_hooks(lab):
    service, author, exp, branches, _ = society_lab(lab)
    task = service.create_task(
        TaskCreate(branch_id=branches[0]["id"], objective="Society objective"), author, "task"
    )
    result, seen = await run_worker(service, author, task["id"])
    assert result["status"] == "completed"
    assert not {"turn_note", "stagnation_suggestions"} & set(seen["kwargs"])
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_society_scaffolding.py tests/test_society_tools.py -q -k "removed_fields or no_check_in"`
Expected: FAIL (the fields validate; the kwargs contain `turn_note`).

- [ ] **Step 3: Implement**
  - `domain.py`, after `StrictModel`:

```python
def _refuse_removed(data: Any, removed: dict[str, str], model: str) -> Any:
    """A ``mode="before"`` guard: an old plan that sets a removed field gets a message that
    names it, not extra="forbid"'s generic one (S1 audit remediation, ruling G2)."""
    if isinstance(data, dict):
        present = sorted(set(data) & set(removed))
        if present:
            field = present[0]
            raise ValueError(
                f"{model}.{field} was removed ({removed[field]}). Delete it from the plan."
            )
    return data

REMOVED_SCAFFOLDING_FIELDS = {
    "checkin_every_turns": "check-ins were acted on 20% of the time and fed the broadcast",
    "stagnation_nudges": "nudges never fired; the stagnation detector stays",
}
```

    and `ScaffoldingPolicy` keeps `playbook` and `skills` only, plus:

```python
    @model_validator(mode="before")
    @classmethod
    def removed_fields(cls, data: Any) -> Any:
        return _refuse_removed(data, REMOVED_SCAFFOLDING_FIELDS, "ScaffoldingPolicy")
```

  - `society_prompt.py`: `BOUNDARIES[2]` becomes `"Harness notes are optional guidance; you decide what to do."`; delete the four functions.
  - `research_worker.py`: import only `constitution` and `referee_constitution` from `.society_prompt`; delete the `if society:` block that sets `turn_note` and `stagnation_suggestions` (`:1728-1748`). The stagnation detector (`stagnation_state`, the `stagnation_recovery` handoff, `RESEARCH_STAGNATION_EXHAUSTED`) is untouched.
  - Remove `checkin_every_turns` and `stagnation_nudges` from `run-plan.example.json`'s `scaffolding` block.
- [ ] **Step 4: Update the tests that pinned the removed behaviour**
  - `tests/test_society_scaffolding.py`: drop the removed names from the import at `:25-33`; delete `test_checkin_note_and_suggestions_are_short_optional_guidance` and `test_referee_checkin_note_and_suggestions_offer_only_referee_work`; remove the two keys from `_policy()`. Keep the runtime-hook tests (`:204-460`); where one imported a removed function only for its text, pass a literal string instead.
  - `tests/test_society_tools.py`: drop the removed imports; in `test_worker_society_prompt_contains_constitution_and_frontier` and `test_worker_referee_prompt_uses_referee_texts` use `society_lab(lab)` without `scaffolding=` and delete the `stagnation_suggestions`/`turn_note` assertions (Task 7 rewrites both tests).
- [ ] **Step 5: Docs.** `PLAN.md` §3.7: replace the check-in and nudge bullets with "Check-ins and stagnation nudges were removed after S1 (acted on 20% of the time; nudges never fired). The stagnation detector remains the loop guard." `docs/RESEARCH_NETWORK.md`: delete "Optional check-ins and stagnation nudges are switched per campaign." `RUN_PLAN.md`: where it lists the S1 scaffolding settings, add "(S1 only; removed in the S1 remediation)".
- [ ] **Step 6: Run the tests**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_society_scaffolding.py tests/test_society_tools.py tests/test_run_control.py tests/test_execution_responses.py -q`
Expected: PASS (`tests/test_run_control.py` validates the edited example plan).

- [ ] **Step 7: Commit**

```bash
git add src/physharness/domain.py src/physharness/orchestration/society_prompt.py src/physharness/orchestration/research_worker.py work/society-s1/run-plan.example.json work/society-s1/RUN_PLAN.md PLAN.md docs/RESEARCH_NETWORK.md tests/test_society_scaffolding.py tests/test_society_tools.py
git -c user.name=Kieran -c user.email=88352982+zubadestroyer1@users.noreply.github.com commit -m "feat: remove society check-ins and stagnation nudges" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Remove labs; messages to a branch or a node's workers, rate-limited (#15)

**Files:**
- Modify: `src/physharness/domain.py:114-123` (`SocietyPolicy`)
- Modify: `src/physharness/workforce.py:13-25` (imports, `LAB_NAME`), delete `:37-43` (`_lab_not_found`), `:395` and `:444` (`lab` parameter and `_branch_lab` call in `_new_branch_task`), delete `:524-624` (`_lab_filter`, `_branch_lab`, `lab_members`), `:666-667` and `:700` (`recruit_researcher`), `:1237-1238`
- Modify: `src/physharness/workforce_models.py:9-10`, `:57-60`
- Modify: `src/physharness/service.py:1329-1331` (`create_branch`)
- Modify: `src/physharness/collaboration.py:900-920` (delete `_lab_route`), `:937` (its call), `:992-1049` (replace `send_lab_message` with `send_society_message`)
- Modify: `src/physharness/commons.py:167` (`lab` payload key), `:314-329` (author lab lookup), `:600` (`_node_item` key)
- Modify: `src/physharness/commons_review.py:598-604`, `:692-693`
- Modify: `src/physharness/orchestration/society_tools.py:1219-1322` (`recruit`, `message`)
- Modify: `src/physharness/orchestration/research_worker.py:1550-1567` (`society_context`: drop `lab`)
- Modify: `work/society-s1/run-plan.example.json:84-85`, `work/society-s1/RUN_PLAN.md:39` (`lab_size_max 6` → note it applied to S1 only), `PLAN.md` §2.4 (`:87-91`), §3.3 (`:134`), §4.1 (`:224`), §4.2 (`:232-233`), §4.6 (`:268-270`), §8 (`:377`), §10 (`:404`); `docs/RESEARCH_NETWORK.md:115,222-228` and the tool table
- Test: delete `tests/test_labs.py`; create `tests/test_society_messages.py`; update `tests/test_society_tools.py:1175,1182,1237,1320-1321`, `tests/test_commons.py:105-128`, `tests/test_society_simulation.py:241,294,438`, `tests/test_commons_review.py:190,222-223,322`, `tests/test_commons_postgresql.py:77`, `tests/test_run_control.py:229-234`, `tests/test_society_scaffolding.py:64-78`, `tests/test_society_metrics.py:133-136,246`

**Interfaces:**
- Consumes: `domain._refuse_removed` (Task 5); `society_tools.ident` (Task 4); `CommonsDiscourseMixin._active_claims(session, node_id)`.
- Produces: `SocietyPolicy.messages_per_minute: int = 12` (1–600); `domain.REMOVED_SOCIETY_FIELDS`; `CollaborationMixin.send_society_message(branch_id: str, to: str, content: str, artifact_ids: list[str], actor, key) -> {"to", "node_id", "message_ids", "recipients"}`; `collaboration.MAX_NODE_RECIPIENTS = 8`; error codes `MESSAGE_RATE_LIMIT` (429) and `NO_RECIPIENTS` (409). Society message payloads carry `node_id` when sent to a node. Branch and node payloads no longer carry `lab`; stored S1 `lab` keys are ignored. `tools/society_metrics.py` keeps its `branches.labs` count so S1 exports stay comparable.

- [ ] **Step 1: Write the failing tests** (`tests/test_society_messages.py`)

```python
"""Society messages (S1 audit #15): no labs; one branch or a node's workers; rate-limited."""

import pytest
from commons_helpers import society_lab
from sqlalchemy import select
from test_society_tools import clock  # noqa: F401

from physharness.commons_models import NodeCreate
from physharness.errors import HarnessError
from physharness.storage import RecordRow

def lemma(service, exp, author, key):
    return service.create_node(
        exp["id"], NodeCreate(node_type="lemma", title=key, statement=key + " holds."), author, key
    )

def test_direct_message_reaches_any_branch(lab):
    service, _, exp, branches, (alpha, beta) = society_lab(lab)
    assert "lab" not in branches[0]
    sent = service.send_society_message(
        alpha.branch_id, beta.branch_id, "Try the coin theorem.", [], alpha, "m1"
    )
    assert sent["recipients"] == [beta.branch_id] and sent["node_id"] is None
    batch = service.discussion_updates(exp["id"], beta)
    assert [item["id"] for item in batch["items"]] == sent["message_ids"]

def test_node_message_reaches_its_author_and_live_claimants_only(lab, clock):  # noqa: F811
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    node = lemma(service, exp, alpha, "trace")
    service.claim_node(node["id"], "claim", beta, "beta-claims")
    sent = service.send_society_message(beta.branch_id, node["id"], "Step 2 fails.", [], beta, "m")
    assert sent["recipients"] == [alpha.branch_id] and sent["node_id"] == node["id"]
    assert service.send_society_message(beta.branch_id, node["id"], "Step 2 fails.", [], beta, "m") == sent
    clock.now += 10_000  # beta's claim lapses
    with pytest.raises(HarnessError) as nobody:
        service.send_society_message(alpha.branch_id, node["id"], "Anyone?", [], alpha, "m2")
    assert nobody.value.code == "NO_RECIPIENTS"

def test_message_rate_limit_is_a_budget_and_the_window_slides(lab):
    service, _, exp, _, (alpha, beta) = society_lab(lab, messages_per_minute=2)
    for index in range(2):
        service.send_society_message(alpha.branch_id, beta.branch_id, "Hi", [], alpha, f"m{index}")
    with pytest.raises(HarnessError) as limited:
        service.send_society_message(alpha.branch_id, beta.branch_id, "Hi", [], alpha, "m2")
    error = limited.value
    assert error.code == "MESSAGE_RATE_LIMIT" and error.status == 429 and error.retryable
    assert "budget, not input: limit 2 per minute, used 2" in error.message
    with service.db.transaction() as session:
        for row in session.scalars(select(RecordRow).where(RecordRow.kind == "message")):
            row.payload = {**row.payload, "created_at": "2000-01-01T00:00:00+00:00"}
    service.send_society_message(alpha.branch_id, beta.branch_id, "Hi", [], alpha, "m3")
```

  Also in this file (specified, write them in the same style): `test_society_policy_names_removed_lab_fields` (parametrized over `lab_size_max` and `cross_lab_direct_messages`: `SocietyPolicy.model_validate({field: 1})` raises a `ValidationError` containing `f"SocietyPolicy.{field} was removed"`); `test_referee_is_unreachable_directly_and_through_a_node` — a referee branch from `request_review` refuses a direct society message with the existing referee-isolation code, and a node message to a node the referee claims (claim through `service.claim_node` as the referee principal) excludes it from `recipients`; `test_node_message_is_capped_at_eight_recipients` — ten claimant branches (create them with `service.create_branch`), `len(recipients) == 8`; `test_recruit_request_has_no_lab` — `"lab" not in RecruitResearcherRequest.model_fields` and a society recruit's branch payload has no `lab`; `test_legacy_send_message_is_unchanged` — `service.send_message` between two branches of `approaches(lab, "ideas")` (from `test_sharing`) has no rate limit (send 20). Move `test_legacy_recruit_fingerprint_and_branch_payload_unchanged` from `tests/test_labs.py` here verbatim with its helpers (`LEGACY_RECRUIT_FIELDS`, `recruit_fingerprint`, `expected_fingerprint`), minus its trailing society-lab part.

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_society_messages.py -q`
Expected: FAIL (`send_society_message` does not exist; branches carry `lab`).

- [ ] **Step 3: Policy.** In `domain.py` remove `lab_size_max` and `cross_lab_direct_messages` from `SocietyPolicy`, add `messages_per_minute: int = Field(default=12, ge=1, le=600)`, and:

```python
REMOVED_SOCIETY_FIELDS = {
    "lab_size_max": "labs were removed; message a branch or a node instead",
    "cross_lab_direct_messages": "labs were removed; any branch may be messaged",
}
```

  with a `removed_fields` `mode="before"` validator on `SocietyPolicy` calling `_refuse_removed(data, REMOVED_SOCIETY_FIELDS, "SocietyPolicy")`.
- [ ] **Step 4: Delete labs.** Remove every item listed under Files for `workforce.py`, `workforce_models.py` (`LAB_PATTERN`, `RecruitResearcherRequest.lab`), `service.create_branch`, `collaboration._lab_route` and its call, `commons.py` (`"lab": None` in `_node_payload`; the `author` lookup and `"lab"` key in `create_node`; `"lab"` in `_node_item`), `commons_review.py` (`lab=None` at `:692-693`; say "whatever the lab policy" no more in `_guard_referee_recipient`'s docstring), `workforce.py:1237-1238`, and `research_worker.society_context`'s `lab` key. `recruit_researcher` fingerprints `data = request.model_dump(mode="json")` (identical to the old dump for legacy requests, which excluded a `None` lab). `_new_branch_task` loses its `lab` parameter; every caller stops passing it.
- [ ] **Step 5: Society messages** (`collaboration.py`, replacing `send_lab_message`). Add `MAX_NODE_RECIPIENTS = 8` and two helpers:
  - `_node_workers(session, node, sender_id) -> list[str]`: the node's author branch, then its live claimants (`self._active_claims(session, node.id)`), dropping the sender, duplicates and any branch whose payload `hat` is `REFEREE_HAT`, capped at `MAX_NODE_RECIPIENTS`.
  - `_message_budget(session, experiment, sender_id, count)`: `limit = experiment.payload["society"].get("messages_per_minute", 12)`; `used` = the count of `message` records of the experiment with `sender_branch_id == sender_id` and `created_at >= (utcnow() - timedelta(seconds=60)).isoformat()`; when `used + count > limit` raise `HarnessError("MESSAGE_RATE_LIMIT", f"Message rate reached (budget, not input: limit {limit} per minute, used {used}).", status=429, retryable=True, details={"limit": limit, "used": used, "requested": count}, remediation="Wait before messaging again, or post on the node's thread (posts are not rate-limited).")`.

  Then:

```python
    def send_society_message(self, branch_id, to, content, artifact_ids, actor, key):
        """Message one branch, or whoever works on a node (its author and live claimants)."""
        self._research_role(actor)
        self._message_text(content)

        def action(session, op):
            sender = self._writable_branch(session, branch_id, actor)
            experiment = self._commons_experiment(session, sender.payload["experiment_id"], actor)
            target = session.get(RecordRow, to)
            node_id = None
            if (
                target is not None
                and target.kind == "commons_node"
                and target.project_id == actor.project_id
                and target.payload.get("experiment_id") == experiment.id
            ):
                node_id, recipients = target.id, self._node_workers(session, target, sender.id)
                if not recipients:
                    raise HarnessError(
                        "NO_RECIPIENTS",
                        "Nobody else works on this node now.",
                        remediation="Post on the node's thread; its followers read it.",
                    )
            else:
                recipients = [to]
            self._message_budget(session, experiment, sender.id, len(recipients))
            records = [
                self._deliver_message(
                    session, op, actor, experiment, sender, recipient, content, artifact_ids,
                    {"node_id": node_id, "delivery_key": f"{key}:{recipient}"} if node_id else {},
                )
                for recipient in recipients
            ]
            return {
                "to": to,
                "node_id": node_id,
                "message_ids": [record["id"] for record in records],
                "recipients": recipients,
            }

        return self._execute(
            actor,
            key,
            "message.society-send",
            {"branch_id": branch_id, "to": to, "content": content, "artifact_ids": artifact_ids},
            action,
        )
```

  (`_deliver_message` keeps `_guard_referee_recipient`, so a direct message to a referee is still refused.)
- [ ] **Step 6: Tools.** `society_tools.py`: `recruit` loses `lab` (property, argument, default, result key and the `LAB_FULL` sentence of its description). `message` becomes:

```python
    def message(a, k):
        return service.send_society_message(
            branch_id, a["to"], a["content"], a["artifact_ids"], agent, k
        )

    add(
        "message",
        {
            "to": ident(
                "A branch id, or a node id to reach whoever works on it.",
                ("branch", "commons_node"),
            ),
            "content": text(20000, "The message."),
            "artifact_ids": array(ident("An artifact id.", ("artifact",)), 12, "Attached evidence."),
        },
        message,
        "Send an attributed message to one branch, or to whoever works on a node (its author "
        "and live claimants, at most 8). Rate-limited per sender; node threads are not. "
        "Messages are unverified ideas.",
        defaults={"artifact_ids": []},
    )
```

- [ ] **Step 7: Tests that encoded labs.** Delete `tests/test_labs.py`. Remove `lab_size_max=`/`cross_lab_direct_messages=` arguments and lab assertions at the listed lines (`test_commons_review.py:322` keeps its referee-isolation assertions without `cross_lab_direct_messages=True`; `test_society_tools.py` deletes `test_message_lab_routing` and `test_recruit_into_full_lab_suggests_new_lab` and drops the lab roster assertions at `:1320-1321`; `test_run_control.py` `SOCIETY` drops `lab_size_max`; `test_society_scaffolding._policy` drops the two keys; `test_society_metrics.py` keeps reading `lab` from its synthetic S1-shaped export). Add to `tests/test_run_control.py` a test that `society_plan()` with `"lab_size_max": 6` in `society` fails `RunPlan.model_validate` with "SocietyPolicy.lab_size_max was removed".
- [ ] **Step 8: Docs.** PLAN.md §2.4 replace the Labs bullet with: "**No labs (S1 remediation).** Labs blocked the one useful hand-off in S1 and decided nothing else. Sparsity now comes from relevance routing (updates reach a node's author, claimants, citers and dependents, never a goal-thread broadcast), a per-sender message rate limit (`messages_per_minute`), and declared alternative routes at genuine choice points (§4.4)." §3.3: `message` (a branch or a node's workers). §4.1: drop "labs". §4.2 step 2: "Each distinct approach becomes an approach node." §4.6: "The campaign budget is split into agent reservations; sub-budgets by graph region remain future work." §8: drop "labs". §10 herding row: "Relevance routing, message rate limit, declared alternative routes, fresh-eyes reseeding, cross-model referees". `docs/RESEARCH_NETWORK.md`: delete the node-lab sentence and the Labs bullet; add a Messages bullet with the rules above; update the tool table's `message` row.
- [ ] **Step 9: Run the tests**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_society_messages.py tests/test_society_tools.py tests/test_commons.py tests/test_commons_review.py tests/test_commons_postgresql.py tests/test_society_simulation.py tests/test_society_metrics.py tests/test_run_control.py tests/test_society_scaffolding.py tests/test_research_workforce.py tests/test_sharing.py -q`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add -A src/physharness work/society-s1 PLAN.md docs/RESEARCH_NETWORK.md tests
git -c user.name=Kieran -c user.email=88352982+zubadestroyer1@users.noreply.github.com commit -m "feat: replace labs with branch- and node-addressed, rate-limited society messages" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

  (Check `git status` first: `-A` on those paths must stage only this task's files, including the deletion of `tests/test_labs.py`.)

---

### Task 7: One lean society prompt view for the prompt and the compaction anchor (#18)

**Files:**
- Create: `src/physharness/orchestration/society_brief.py`
- Modify: `src/physharness/orchestration/research_worker.py:14-18` (imports), delete `:434-452` (`SOCIETY_CAPACITY_NOTE`, `REFEREE_CAPACITY_NOTE`, `SOCIETY_SOURCE_RETRIEVAL`), `:1550-1592` (delete `society_context` and the society branch of `collaboration_context`), `:1594-1650` (`context_anchor`), `:1788-1844` (prompt)
- Modify: `src/physharness/commons_review.py:94-98` (delete `REFEREE_FRONTIER_NOTE`)
- Modify: `docs/RESEARCH_NETWORK.md` (the "The prompt carries …" paragraph), `PLAN.md` §3.2 (`:120-124`)
- Test: `tests/test_society_tools.py:1292-1400` (rewrite both prompt tests), `:1555-1575` (`scripted_society_route` role detection)

**Interfaces:**
- Consumes: `service.query_nodes(experiment_id, actor, frontier=True, limit=5) -> {"items", "next_cursor", ["long_pole"]}` (`long_pole` appears in Task 16), `service.branch_claims`, `service.joined_task_statuses`, `service.delegated_task_statuses`.
- Produces: `society_brief.TARGET_FIELDS = ("title", "informal_statement", "formal_statement", "target_theorem", "assumptions", "definitions")`; `society_brief.society_prompt_view(service, *, experiment: dict, task: dict, agent: Principal, referee: bool, ready: dict | None, handoff_notes: dict | None, instructions: str) -> dict`. A builder's view has `objective`, `target`, `instructions`, and only the non-empty of `frontier` (list of `"<id8> [<type>] <title>"`), `long_pole`, `focus_nodes`, `strategy`, `models`, `synthesis`, `continuation` (`{"reason", "ordinal"}`), `handoff_notes`, `joined_results`. A referee's view has exactly `objective` (the fenced packet), `target`, `instructions`.

- [ ] **Step 1: Write the failing tests** (replace `test_worker_society_prompt_contains_constitution_and_frontier` and `test_worker_referee_prompt_uses_referee_texts`; import `society_prompt_view` and `NODE_DATA_BEGIN`)

```python
async def test_society_prompt_is_the_lean_view_and_the_anchor_matches(lab):
    service, author, exp, branches, (alpha, _beta) = society_lab(lab)
    node = service.create_node(
        exp["id"],
        NodeCreate(node_type="lemma", title="Trace lemma", statement="The trace is additive."),
        alpha,
        "node",
    )
    service.claim_node(node["id"], "claim", alpha, "focus")
    task = service.create_task(
        TaskCreate(branch_id=branches[0]["id"], objective="Society objective"), author, "task"
    )
    result, seen = await run_worker(service, author, task["id"])
    assert result["status"] == "completed"
    content = seen["payloads"][0]["input"][0]["content"]
    prompt = json.loads(content)
    assert prompt == json.loads(seen["anchors"][0])
    assert set(prompt) == {"objective", "target", "instructions", "frontier", "focus_nodes"}
    assert set(prompt["target"]) == set(society_brief.TARGET_FIELDS)  # canonical_json sorts keys
    assert prompt["instructions"] == constitution(exp["society"], literature_enabled=False)
    line = f"{node['id'][:8]} [lemma] Trace lemma"
    assert line in prompt["frontier"] and prompt["focus_nodes"] == [line]
    assert len(content) < len(json.dumps(prompt["target"])) + len(prompt["instructions"]) + 1500

async def test_referee_prompt_is_packet_target_and_referee_constitution(lab):
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    node = service.create_node(
        exp["id"],
        NodeCreate(node_type="lemma", title="Trace lemma", statement="The trace is additive."),
        alpha,
        "node",
    )
    requested = service.request_review(node["id"], "informal", beta, "review")
    result, seen = await run_worker(service, author, requested["review_task_id"])
    assert result["status"] == "completed"
    prompt = json.loads(seen["payloads"][0]["input"][0]["content"])
    task = service.get_record("task", requested["review_task_id"], author)
    assert set(prompt) == {"objective", "target", "instructions"}
    assert prompt["objective"] == task["objective"]
    assert prompt["objective"].count(NODE_DATA_BEGIN) == 1
    assert prompt["instructions"] == referee_constitution(exp["society"], literature_enabled=False)
    assert prompt == json.loads(seen["anchors"][0])
```

  Also (specified): `test_prompt_view_carries_continuation_and_lists_only_distinct_models` — call `society_prompt_view` directly for a task of `society_lab(lab, models=2)` with `ready={"reason": "root_unproved_replan", "ordinal": 2}` and `handoff_notes={"checkpoint_id": "c"}`: the view has `continuation == {"reason": "root_unproved_replan", "ordinal": 2}`, those `handoff_notes`, and `models` indexed `[0, 1]`; for a one-model experiment (`society_lab(lab, prefix="one")`) with `ready=None` it has neither `models` nor `continuation`.

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_society_tools.py -q -k "lean_view or packet_target or distinct_models"`
Expected: FAIL (`society_brief` does not exist; the prompt still has `research_brief`).

- [ ] **Step 3: The view** (`src/physharness/orchestration/society_brief.py`)

```python
"""A society agent's prompt and compaction anchor (S1 audit #18): the target, the objective,
the constitution and the live frontier, without platform bookkeeping. Legacy prompts are
built in research_worker and never come here."""

from ..domain import canonical_json

TARGET_FIELDS = (
    "title",
    "informal_statement",
    "formal_statement",
    "target_theorem",
    "assumptions",
    "definitions",
)
FRONTIER_ITEMS = 5
FOCUS_ITEMS = 10

def _line(node_id, node_type, title):
    return f"{node_id[:8]} [{node_type}] {title[:120]}"

def society_prompt_view(
    service, *, experiment, task, agent, referee, ready, handoff_notes, instructions
):
    target = service.get_record("problem", experiment["problem_id"], agent)
    view = {
        "objective": task["objective"],
        "target": {field: target.get(field) for field in TARGET_FIELDS},
        "instructions": instructions,
    }
    if referee:
        return view  # the fenced review packet is the referee's objective
    frontier = service.query_nodes(experiment["id"], agent, frontier=True, limit=FRONTIER_ITEMS)
    focus = service.branch_claims(experiment["id"], agent, limit=FOCUS_ITEMS)["items"]
    models = experiment["models"]
    joined = [item["task_id"] for item in service.joined_task_statuses(task["id"], agent)["children"]]
    optional = {
        "frontier": [_line(i["id"], i["node_type"], i["title"]) for i in frontier["items"]],
        "long_pole": frontier.get("long_pole"),
        "focus_nodes": [_line(i["node_id"], i["node_type"], i["title"]) for i in focus],
        "strategy": task.get("strategy"),
        "models": [{"index": index, "model": model["model"]} for index, model in enumerate(models)]
        if len({canonical_json(model) for model in models}) > 1
        else None,
        "synthesis": {
            "source_post_ids": task.get("discussion_refs") or [],
            "scope": task.get("synthesis_scope"),
        }
        if task.get("synthesis_scope")
        else None,
        "continuation": {"reason": ready["reason"], "ordinal": ready["ordinal"]} if ready else None,
        "handoff_notes": handoff_notes,
        "joined_results": service.delegated_task_statuses(task["id"], joined, agent)
        if joined
        else None,
    }
    view.update({key: value for key, value in optional.items() if value})
    return view
```

- [ ] **Step 4: Wire it** (`research_worker.py`)
  - Import `society_prompt_view` from `.society_brief`; delete the three society constants and the `REFEREE_FRONTIER_NOTE` import; delete `society_context` and make `collaboration_context` legacy-only (its body minus the `if society:` branch).
  - Define, next to `research_instructions`:

```python
            def society_view():
                return society_prompt_view(
                    self.service,
                    experiment=experiment,
                    task=task,
                    agent=agent,
                    referee=referee,
                    ready=ready,
                    handoff_notes=PortableMemory(self.service).handoff_notes(
                        branch["id"], agent, task_id=task_id
                    ),
                    instructions=research_instructions,
                )
```

  - `context_anchor`: after the `TARGET_CHANGED` check, `if society: return canonical_json(society_view())`; the legacy dict follows unchanged.
  - Prompt: keep the `handoff_notes` fetch and its `CONTINUATION_STALE` check for both profiles; compute `brief` only for legacy; then `prompt = canonical_json(society_view()) if society else canonical_json({...the existing legacy dict...})`. The legacy dict's keys and order stay byte-identical.
  - Delete `REFEREE_FRONTIER_NOTE` from `commons_review.py` (nothing else reads it).
- [ ] **Step 5: Update callers of the old prompt shape.** `scripted_society_route` (`tests/test_society_tools.py:1566`): `role = "referee" if prompt["instructions"].startswith("Research society referee") else "root"`. Then run `grep -rn "commons_frontier\|capacity_guidance\|review_assignment\|research_brief\|peer_source_retrieval" tests/` and update each society-profile use to the new keys (legacy tests stay).
- [ ] **Step 6: Docs.** `docs/RESEARCH_NETWORK.md`: "A society prompt holds the task objective, the target's six fields (title, informal and formal statement, target theorem, assumptions, definitions), the constitution, and when non-empty the top five frontier lines, the long pole, the agent's claimed nodes, its strategy, the models (when they differ), the synthesis scope, the continuation reason and ordinal, its handoff notes and joined results. The compaction anchor is the same view, re-read live. A referee's prompt is its fenced review packet, the target and the referee constitution." `PLAN.md` §3.2 item 1: add "(the society anchor is the same lean view as its prompt)".
- [ ] **Step 7: Run the tests**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_society_tools.py tests/test_society_simulation.py tests/test_swarm_coordination_gaps.py tests/test_joined_delegation.py tests/test_network_runtime.py -q`
Expected: PASS, including `test_worker_legacy_prompt_unchanged`.

- [ ] **Step 8: Commit**

```bash
git add src/physharness/orchestration/society_brief.py src/physharness/orchestration/research_worker.py src/physharness/commons_review.py docs/RESEARCH_NETWORK.md PLAN.md tests/test_society_tools.py
git -c user.name=Kieran -c user.email=88352982+zubadestroyer1@users.noreply.github.com commit -m "feat: build society prompts and anchors from a lean view of target, objective and frontier" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Relevance-routed, echo-free, compact updates; a pull-only goal thread (#13)

**Files:**
- Modify: `src/physharness/commons_discourse.py:151-217` (`claim_node`: goal refusal, `co_claimants`), `:255-274` (`_auto_subscribe`: skip the goal thread), `:468-488` (`_node_thread_item`: `node_title`), new module function `compact_update_lines`
- Modify: `src/physharness/discussion.py:436-446` (post event `branch_id` for node threads), `:675-822` (`discussion_updates`: skip, cursor), new `_push_skip`
- Modify: `src/physharness/commons.py:477-521` (`read_node(node_id, actor, *, before=None)`: `recent_posts`, `older_before`)
- Modify: `src/physharness/orchestration/research_network.py:284-307` (`render`)
- Modify: `src/physharness/execution/responses.py:301-367` (`_receive_updates`: `rendered`)
- Modify: `src/physharness/orchestration/research_worker.py:1723-1727` (`render` for society builders)
- Modify: `src/physharness/orchestration/society_tools.py:983-1007` (`commons_read.before`), `:1186-1195` (`commons_claim` description); `src/physharness/orchestration/society_prompt.py:13-21` (`NORMS`)
- Modify: `docs/RESEARCH_NETWORK.md:71-94` (Delivery) and "Threads and digests", `PLAN.md` §2.4 Delivery (`:82-86`)
- Test: create `tests/test_relevance_routing.py`; update `tests/test_commons_review.py:1483-1510`, `tests/test_society_scaffolding.py` (NORMS list), `tests/test_society_simulation.py`

**Interfaces:**
- Consumes: `service.resolve_id` (Task 4) for the 8-hex ids agents copy from lines.
- Produces: error `GOAL_NOT_CLAIMABLE`; claim results gain `co_claimants: [{"branch_id", "expires_at"}]`; node-thread delivery items gain `node_title`; `discussion.post_created` events on node threads carry `branch_id`; `DiscussionMixin._push_skip(post: dict, item: dict, actor) -> bool` and `DiscussionMixin._delivery_clauses(session, experiment, actor, reader_key, ack) -> list` (both reused by Task 16); `commons_discourse.COMPACT_HEADER` and `compact_update_lines(items: list[dict]) -> str`; `discussion_delivery_hooks(service, agent, task_id, holder, fence, *, render=None)`; a batch key `rendered: str` that `_receive_updates` persists instead of the JSON envelope; `read_node` gains `recent_posts: list[str]` and `older_before: int | None`; `commons_read` gains `before`.

- [ ] **Step 1: Write the failing tests** (`tests/test_relevance_routing.py`)

```python
"""S1 audit #13: relevance-routed, echo-free, compact updates; the goal thread is pull-only."""

import pytest
from commons_helpers import society_lab
from test_execution_responses import message
from test_research_loop_integration import tool_call
from test_society_tools import run_worker

from physharness.commons_discourse import COMPACT_HEADER, compact_update_lines
from physharness.commons_models import NodeCreate, NodePostCreate
from physharness.domain import TaskCreate
from physharness.errors import HarnessError

def node(service, exp, author, title, key):
    return service.create_node(
        exp["id"], NodeCreate(node_type="lemma", title=title, statement=title + " holds."), author, key
    )

def post(service, node_id, author, key, abstract="A finding."):
    return service.post_on_node(node_id, NodePostCreate(kind="finding", abstract=abstract), author, key)

def test_goal_is_not_claimable_and_its_thread_is_pull_only(lab):
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    goal = service.query_nodes(exp["id"], alpha, node_type="goal")["items"][0]
    with pytest.raises(HarnessError) as error:
        service.claim_node(goal["id"], "claim", alpha, "claim-goal")
    assert error.value.code == "GOAL_NOT_CLAIMABLE"
    post(service, goal["id"], alpha, "a-goal", abstract="Plan: split existence and rate.")
    post(service, goal["id"], beta, "b-goal")
    assert service.discussion_updates(exp["id"], alpha)["items"] == []
    assert service.discussion_updates(exp["id"], beta)["items"] == []
    recent = service.read_node(goal["id"], alpha)["recent_posts"]
    assert len(recent) == 2 and "Plan: split existence and rate." in recent[0]  # oldest first

def test_own_posts_are_skipped_and_the_cursor_advances(lab):
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    lemma = node(service, exp, alpha, "Trace lemma", "lemma")
    claim = service.claim_node(lemma["id"], "claim", beta, "beta-claims")
    assert claim["co_claimants"] == []
    post(service, lemma["id"], alpha, "own")
    empty = service.discussion_updates(exp["id"], alpha)
    assert empty["delivery_id"] is None and empty["items"] == []
    assert service.list_records("discussion_delivery", author, exp["id"]) == []
    peer = post(service, lemma["id"], beta, "peer")
    batch = service.discussion_updates(exp["id"], alpha)
    assert [item["id"] for item in batch["items"]] == [peer["id"]]
    assert batch["items"][0]["node_title"] == "Trace lemma"

def test_compact_lines_are_one_bounded_line_per_item():
    item = {
        "id": "1234abcd-0000-4000-8000-000000000000", "source_kind": "discussion_post",
        "post_kind": "objection", "branch_id": "9c0d1e2f-0000-4000-8000-000000000000",
        "node_id": "5e6f7a8b-0000-4000-8000-000000000000", "node_title": "Trace lemma",
        "excerpt": "x" * 600, "truncated": True, "urgent": True,
    }
    text = compact_update_lines([item])
    header, line = text.split("\n")
    assert header == COMPACT_HEADER
    assert line.startswith('! [objection] on 5e6f7a8b "Trace lemma" from 9c0d1e2f: ')
    assert line.endswith("(post_id 1234abcd)") and len(line) <= 320

async def test_society_worker_receives_compact_update_lines(lab):
    service, author, exp, branches, (alpha, beta) = society_lab(lab)
    lemma = node(service, exp, alpha, "Trace lemma", "lemma")
    peer = post(service, lemma["id"], beta, "peer", abstract="The trace is additive: see step 2.")
    task = service.create_task(TaskCreate(branch_id=branches[0]["id"], objective="Obj"), author, "t")

    def script(phase, payload):
        if phase == 0:
            return [tool_call("commons_query", {"frontier": True}, "q-1")]
        return [message("done")]

    result, seen = await run_worker(service, author, task["id"], script)
    assert result["status"] == "completed"
    updates = [
        item["content"]
        for item in seen["payloads"][-1]["input"]
        if item.get("role") == "user" and str(item.get("content", "")).startswith(COMPACT_HEADER)
    ]
    [update] = updates
    line = update.split("\n")[1]
    assert line.startswith(f'[finding] on {lemma["id"][:8]} "Trace lemma"')
    assert line.endswith(f"(post_id {peer['id'][:8]})") and '"notice"' not in update
```

  Also (specified): `test_leading_own_posts_do_not_starve_later_updates` — 101 own posts on alpha's node, then one beta post; the first `discussion_updates(alpha)` returns no items and advances `ack_sequence`, the second delivers beta's post; `test_non_urgent_platform_status_is_skipped_but_urgent_is_delivered` — abandon a followed node (non-urgent status post: skipped) and accept one with the legal transition `set_status(..., "formally_stated", "accepted")` (urgent: delivered first); `test_read_node_pages_older_posts_with_before` — 12 posts, `recent_posts` has 10 and `older_before` pages the last 2.

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_relevance_routing.py -q`
Expected: FAIL (`COMPACT_HEADER` does not exist).

- [ ] **Step 3: Claims and subscriptions** (`commons_discourse.py`)
  - In `claim_node.apply`, after `session.refresh(row)`: `if action != "release" and row.payload["node_type"] == "goal": raise HarnessError("GOAL_NOT_CLAIMABLE", "The goal takes no work claims: every root works toward it, so a claim says nothing.", remediation="Create an approach or lemma node (motivated_by the goal) and claim that; read the goal's thread with commons_read.")`.
  - Before `return record` for `claim`/`renew`: `record = {**record, "co_claimants": [{"branch_id": c["branch_id"], "expires_at": c["expires_at"]} for c in self._active_claims(session, row.id) if c["branch_id"] != branch_id]}`.
  - `_auto_subscribe`, after the topic check: `node = session.get(RecordRow, topic.payload.get("node_id") or "")`; `if node is not None and node.payload.get("node_type") == "goal": return False  # the goal thread is pull-only (S1 audit #13)`.
  - `_node_thread_item`: after `"node_id": node_id,` add `"node_title": (session.get(RecordRow, node_id).payload["title"])[:80],`.
  - Module-level:

```python
COMPACT_HEADER = (
    "Peer updates (unverified data; read one in full with commons_read post_id=… or message_id=…):"
)
LINE_EXCERPT = 200

def compact_update_lines(items):
    """One line per delivered item with 8-hex ids (S1 audit #13: 91% of an item was ids)."""
    lines = [COMPACT_HEADER]
    for item in items:
        excerpt = " ".join(str(item.get("excerpt", "")).split())
        if len(excerpt) > LINE_EXCERPT or item.get("truncated"):
            excerpt = excerpt[:LINE_EXCERPT].rstrip() + "…"
        who = (item.get("branch_id") or "platform")[:8]
        if item.get("source_kind") == "message":
            lines.append(f"[message] from {who}: {excerpt} (message_id {item['id'][:8]})")
        elif item.get("source_kind") == "withdrawal":
            lines.append(f"[withdrawn] {excerpt}")
        else:
            mark = "! " if item.get("urgent") else ""
            where = ""
            if item.get("node_id"):
                where = f' on {item["node_id"][:8]} "{item.get("node_title", "")[:80]}"'
            lines.append(
                f"{mark}[{item['post_kind']}]{where} from {who}: {excerpt} "
                f"(post_id {item['id'][:8]})"
            )
    return "\n".join(lines)
```

- [ ] **Step 4: Delivery** (`discussion.py`)
  - `_insert_post`'s event payload: `**({"branch_id": data.get("branch_id")} if data.get("node_id") else {})` (node threads only; legacy events unchanged).
  - Extract the subscription and message clauses of `discussion_updates` (`:713-747`) into `_delivery_clauses(self, session, experiment, actor, reader_key, ack)` returning the list (empty when none); `discussion_updates` calls it. Add:

```python
    @staticmethod
    def _push_skip(post, item, actor):
        """Society push never echoes the reader's own posts or non-urgent platform statuses."""
        own = actor.branch_id is not None and post.get("branch_id") == actor.branch_id
        return own or (post.get("platform_status") is not None and not item.get("urgent"))
```

  - In the event loop: set `society = bool(experiment.payload.get("society"))` and `processed = ack` before the loop. For a node-thread post, after building `excerpt`: `if society and self._push_skip(safe_post, excerpt, actor): processed = event.sequence; continue`. After `items.append(excerpt)` set `processed = event.sequence`.
  - After the loop:

```python
            if not items:
                if processed > ack:  # only skipped events: advance past them, deliver nothing
                    self._replace(session, reader, {"ack_sequence": processed})
                return {"delivery_id": None, "items": [], "next_cursor": processed, "redelivered": False}
            end = processed  # the highest sequence handled; equals the last item without skips
```

    (Without skips `processed` equals the last included sequence, so legacy deliveries are unchanged.)
- [ ] **Step 5: Pull digest** (`commons.py` `read_node`): add `before: int | None = None`; inside the session, when the node has a `topic_id`, select the 11 newest `discussion.post_created` events for that topic (`EventRow.sequence < before` when given), load each post, and render `f"{post.id[:8]} [{p['post_kind']}] from {(p.get('branch_id') or 'platform')[:8]}: {' '.join((p.get('abstract') or p['content']).split())[:200]}"`; return the first 10 oldest-first as `recent_posts` and `older_before` = the smallest shown sequence when an 11th exists, else `None`. `commons_read` passes `before` (an `integer(1, 2**53, "node_id: page older thread posts.", nullable=True)`, default `None`) to `read_node`.
- [ ] **Step 6: Render at the runtime boundary**
  - `research_network.discussion_delivery_hooks(..., *, render=None)`: after fetching, `if render is not None and batch["items"]: batch = {**batch, "rendered": render(batch["items"])}`.
  - `responses._receive_updates`: build `encoded` from `batch.get("rendered")` when it is present (it must be a non-empty `str`, else `INVALID_UPDATES`), otherwise the existing JSON envelope; the 16 KiB bound, fingerprint, save and ack apply to `encoded` unchanged.
  - `research_worker.py:1723`: pass `render=compact_update_lines if society and not referee else None` (referees keep the fenced JSON envelope).
- [ ] **Step 7: Norm, description, old tests.** `NORMS[2]` becomes `"Claim the node you work on before sinking effort (the goal takes no claims; read its thread on demand)."`; update the NORMS copy in `tests/test_society_scaffolding.py`. `commons_claim` description: "…several branches may hold one; the goal takes none. The result lists your co-claimants." `tests/test_commons_review.py::test_goal_accepted_hook_on_verified_target_receipt`: drop the goal claim and the `drain` assertions about a pushed goal status post (the goal thread is pull-only); keep the status assertions.
- [ ] **Step 8: Docs.** `docs/RESEARCH_NETWORK.md` Delivery and "Threads and digests": society deliveries are compact lines with 8-hex ids; never the reader's own posts; non-urgent platform statuses are not pushed; the goal takes no claims and nobody follows its thread (read it with `commons_read(node_id=<goal>)`, `before` pages older posts). PLAN.md §2.4 Delivery: same, and "the goal thread is a pull-only digest".
- [ ] **Step 9: Run the tests**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_relevance_routing.py tests/test_research_discussion.py tests/test_commons_discourse.py tests/test_commons_review.py tests/test_network_runtime.py tests/test_society_tools.py tests/test_society_simulation.py tests/test_society_scaffolding.py -q`
Expected: PASS, including `test_legacy_discussion_delivery_shape_unchanged`.

- [ ] **Step 10: Commit**

```bash
git add src/physharness tests docs/RESEARCH_NETWORK.md PLAN.md
git -c user.name=Kieran -c user.email=88352982+zubadestroyer1@users.noreply.github.com commit -m "feat: route society updates by relevance as compact lines; make the goal thread pull-only" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 9: The lemma store: node modules and ranked `lean_source` publication (#12a)

**Files:**
- Create: `src/physharness/commons_sources.py` (`CommonsSourceMixin`, rank rule, module naming)
- Modify: `src/physharness/service.py:116-125` (add `CommonsSourceMixin` to `HarnessService`)
- Modify: `src/physharness/commons.py:143-173` (`_node_payload`: `lean_module`, `lean_source`), `:298-364` (`create_node`: assign the module; event payload gains `branch_id`), `:597-605` (`_node_item`: `module`, `source`), `:643-709` (`query_nodes`: corpus and `source` filter)
- Modify: `src/physharness/commons_review.py:717-757` (`referee_may_read_artifact`: the node's `lean_source.artifact_id`)
- Modify: `src/physharness/orchestration/society_tools.py:326-372` (helpers), `:619-694` (`lean_check`, `publish`, `claim`; `local_compile` takes the verdict), `:955-981` (`commons_query.source`)
- Modify: `src/physharness/memory.py` (`working_context`'s `source_rows` query, ~`:490-510`): a node module is a `lean_source` artifact too, so its candidate-picking skips one whose `provenance` has a `node_id` (a lemma's module, not the branch's own submission candidate)
- Modify: `docs/RESEARCH_NETWORK.md` (society section: a "Lemma store" bullet)
- Test: create `tests/test_commons_sources.py`; `tests/test_society_tools.py` (`FakeLean.__init__` sets `self.sources = []` and `check` appends each source; new tests); `tests/test_memory.py` (new test below)

**Interfaces:**
- Consumes: `HarnessService._prefix_candidates` (Task 4), `_review_node`, `_add_edge`, `_touch_node`.
- Produces (in `commons_sources.py`): `RANKS = {"partial": 1, "complete": 2, "verified": 3}`, `COMPLETE_RANKS = frozenset({"complete", "verified"})`, `node_module(node: dict) -> str` (`node.get("lean_module") or "Commons.N" + node["id"][:8]`), `module_prefix(module: str) -> str | None` (the dashed id prefix of `Commons.N<8|12|16 hex>`), `source_state(node: dict) -> str` (the effective rank, `"stub"` for an elaborated statement without a source, else `"none"`); `CommonsSourceMixin.record_lean_source(node_id, artifact_id, record: dict, actor, key) -> dict` returning `{"recorded": True, "module", "rank", "replaced"}` or `{"recorded": False, "module", "reason", ["rank"]}`; `CommonsSourceMixin._module_node(session, module: str, actor, experiment_id) -> RecordRow` (Task 10). `record` keys: `rank`, `bytes`, `statement_check` (`{"ok", "reason", "axioms"}` or `None`), `lean_statement_sha256`, `imports` (`[{"module", "node_id", "sha256"}]`). Node payload `lean_source` keys: `artifact_id`, `sha256`, `bytes`, `branch_id`, `task_id`, `rank`, `statement_check`, `lean_statement_sha256`, `imports`, `recorded_at`. Event `commons.source_published` (`aggregate_id = node_id`, so a watched-node wait wakes on it) `{experiment_id, node_id, branch_id, artifact_id, sha256, rank, replaced}`. `lean_check` with `node_id` returns `published` and `claimed` (plus `local_compile` until Task 12). `society_tools.STATEMENT_REJECTIONS`, `_publication_refusal(source, node, result) -> str | None`, `_source_rank(node, result, verdict) -> str | None`.

- [ ] **Step 1: Write the failing tests.** `tests/test_society_tools.py` (import `node_module` is not needed; use the stored node):

```python
async def test_lean_check_publishes_a_verified_module_for_its_node(lab):
    service, author, exp, _, (alpha, _) = society_lab(lab)
    agent, context = running(service, author, exp, alpha.branch_id)
    tools = profile(service, agent, context, workspace=FakeWorkspace())
    created = await call(tools, "commons_node", lemma_args())
    await call(tools, "commons_node", {"action": "set_lean_statement", "node_id": created["id"], **LEAN})
    checked = await call(tools, "lean_check", {"source": PROOF, "node_id": created["id"]})
    node = service.read_node(created["id"], agent)["node"]
    assert node["lean_module"] == "Commons.N" + created["id"][:8]
    assert checked["published"] == {
        "recorded": True, "module": node["lean_module"], "rank": "verified", "replaced": False
    }
    assert checked["claimed"] is True
    artifact = service.get_record("artifact", node["lean_source"]["artifact_id"], agent)
    assert artifact["artifact_kind"] == "lean_source" and artifact["sha256"] == node["lean_source"]["sha256"]
```

  Also `test_without_a_working_checker_a_source_stops_at_complete`: as above with `workspace.lean.verdict = {"ok": False, "reason": "statement_check_unavailable", "axioms": None, "detail": None, "backend": "lean_statement_check"}`; the rank is `complete` and the stored `statement_check` is `{"ok": False, "reason": "statement_check_unavailable", "axioms": None}`.

  `tests/test_commons_sources.py` (new; imports `pytest`, `society_lab`, `from physharness import commons`, `NodeCreate`, `ArtifactCreate`, `HarnessError`, and from Task 10 on `Expansion`, `Module`, `inline_commons`, `remap` from `physharness.commons_sources`; service level; `publish(service, node_id, agent, rank, key, content=…)` creates a `lean_source` artifact with `service.create_artifact(ArtifactCreate(experiment_id=agent.experiment_id, branch_id=agent.branch_id, kind="lean_source", content=content), agent, key + ":a")` and calls `record_lean_source` with `{"rank": rank, "bytes": len(content), "statement_check": None, "lean_statement_sha256": None, "imports": []}`):

```python
def test_rank_rule_replaces_upward_only(lab):
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    node = service.create_node(exp["id"], NodeCreate(node_type="lemma", title="L", statement="L."), alpha, "n")
    assert publish(service, node["id"], beta, "partial", "p1")["recorded"] is True
    assert publish(service, node["id"], beta, "complete", "c1")["replaced"] is True
    lower = publish(service, node["id"], alpha, "partial", "p2")
    assert lower == {"recorded": False, "module": node["lean_module"], "reason": "lower_rank", "rank": "complete"}
    goal = service.query_nodes(exp["id"], alpha, node_type="goal")["items"][0]
    assert publish(service, goal["id"], alpha, "complete", "g")["reason"] == "goal_node"

def test_modules_are_unique_even_when_ids_share_eight_hex(lab, monkeypatch):
    service, _, exp, _, (alpha, _) = society_lab(lab)
    ids = iter(["abcdef12-1111-4000-8000-000000000001", "abcdef12-2222-4000-8000-000000000002"])
    monkeypatch.setattr(commons, "new_id", lambda: next(ids))
    first = service.create_node(exp["id"], NodeCreate(node_type="lemma", title="A", statement="A."), alpha, "a")
    second = service.create_node(exp["id"], NodeCreate(node_type="lemma", title="B", statement="B."), alpha, "b")
    assert first["lean_module"] == "Commons.Nabcdef12"
    assert second["lean_module"] == "Commons.Nabcdef122222"
```

  Also (specified, same file): `test_verified_source_is_replaced_only_by_its_publisher_or_the_author` (a node with a Lean statement; a third branch from `service.create_branch` cannot replace beta's verified source; beta and the author alpha can); `test_publication_refused_when_the_statement_changed` (record carries the old digest → `reason == "statement_changed"`); `test_import_edges_are_depends_on_and_skip_cycles` (`imports` naming another node adds a `depends_on` edge; a cycle is skipped, not raised); `test_query_matches_lean_name_and_filters_by_source` (`query_nodes(text=<lean_name>)` finds it; `source="complete"` / `"stub"` / `"none"` filter).
- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_commons_sources.py tests/test_society_tools.py -q -k "publish or module or rank or complete"`
Expected: FAIL (no `lean_module`, no `record_lean_source`).

- [ ] **Step 3: Modules** (`commons.py`). `_node_payload` adds `"lean_module": fields.get("lean_module")` and `"lean_source": None`. In `create_node` choose `node_id = new_id()` first and insert with `record_id=node_id` and `lean_module=self._new_module(session, experiment, node_id)`:

```python
    def _new_module(self, session, experiment, node_id):
        """`Commons.N` + 8 hex of the id, lengthened to 12 or 16 when an experiment node
        already holds that name (S1 audit #12; 8 hex collide at ~0.3% for 5,000 nodes)."""
        hexid = node_id.replace("-", "")
        for width in (8, 12, 16):
            module = "Commons.N" + hexid[:width]
            taken = select(RecordRow.id).where(
                RecordRow.project_id == experiment.project_id,
                RecordRow.kind == "commons_node",
                record_json_text("experiment_id") == experiment.id,
                RecordRow.id.startswith(node_id[:8]) if width == 8
                else record_json_text("lean_module") == module,
            ).limit(1)
            if session.scalar(taken) is None:
                return module
        raise HarnessError("COMMONS_MODULE_COLLISION", "No unique module name for this node.")
```

  The `commons.node_created` event payload gains `"branch_id": actor.branch_id`. `_node_item` adds `"module": node_module(node)` and `"source": source_state(node)`. `query_nodes` gains `source: str | None = None` (one of `verified`, `complete`, `partial`, `stub`, `none`; else `INVALID_QUERY`); its text corpus adds `lean_name` and `node_module(node)`.
- [ ] **Step 4: Publication** (`commons_sources.py`). `module_prefix("Commons.N" + h)` returns `h[:8] + "".join("-" + h[i:i + 4] for i in range(8, len(h), 4))` for `len(h) in (8, 12, 16)`, else `None`. `_module_node` filters `self._prefix_candidates(session, module_prefix(module), actor, ("commons_node",))` to the experiment's node whose `node_module` equals `module`, else raises `COMMONS_MODULE_NOT_FOUND` (404, `details={"module"}`, remediation "Import a module name a node reports (commons_read, commons_query)."). `record_lean_source` runs under `self._execute(actor, key, "commons.source_publish", inputs, action)`; `action`:
  1. `row, experiment = self._review_node(session, node_id, actor)`; a goal → `{"recorded": False, "module", "reason": "goal_node"}`; a closed node → reason `node_closed`.
  2. The artifact (`self._get(session, "artifact", artifact_id, actor)`) must be `lean_source`, in the experiment, and from `actor.branch_id`; else `SOURCE_ARTIFACT_SCOPE` (403).
  3. `digest = _lean_digest(header, name, statement)` of the node now (`None` without a statement); when the node has a statement and `record["lean_statement_sha256"] != digest`, return reason `statement_changed`.
  4. Effective rank: a stored `verified` source whose `lean_statement_sha256 != digest` counts as `complete`. Replace when the new rank is higher; at equal rank replace, except that a current `verified` source is replaced only by its publisher branch or the node's author branch. Otherwise return reason `lower_rank` with the current `rank`.
  5. Store `lean_source` (keys under Interfaces; `task_id` from `current_worker_effects.get()`), `last_activity_at`; add a `depends_on` edge to each `imports[].node_id` with `self._add_edge(...)`, catching `HarnessError` with code `DEPENDENCY_CYCLE` or `SELF_EDGE`; `self._touch_node(session, row, actor, op)`; emit `commons.source_published` with `aggregate_id=row.id` (the node), so a wait watching the node wakes on it.
- [ ] **Step 5: `lean_check` publishes** (`society_tools.py`). Add `STATEMENT_REJECTIONS = frozenset({"statement_mismatch", "kernel_rejected", "theorem_missing"})` and:

```python
def _publication_refusal(source, node, result):
    """Why a checked file cannot be the node's module, or None (S1 audit #12)."""
    if node.get("node_type") == "goal":
        return "goal_node"
    if not result["ok"]:
        return "lean_errors"
    if "#exit" in source:
        return "exit_command"
    name, statement = node.get("lean_name"), node.get("lean_statement")
    if name and statement:
        refusal = _compile_refusal(source, node)
        if refusal is not None:
            return refusal
        if not statement_found(source, name, statement):
            return "statement_not_found"
    return None

def _source_rank(node, result, verdict):
    """verified, complete or partial; None when the statement check rejected the file.
    Without a working checker (S1: it never ran) a source stops at complete."""
    if not result["complete"]:
        return "partial"
    name, reported = node.get("lean_name"), result.get("axioms") or {}
    if verdict is None:  # no Lean statement: the file's own axiom report is all there is
        return "complete" if set().union(*reported.values()) <= STANDARD_AXIOMS else "partial"
    if verdict.get("ok"):
        return "verified" if axiom_refusal({name: verdict["axioms"]}, name) is None else "partial"
    if verdict.get("reason") in STATEMENT_REJECTIONS:
        return None
    return "complete" if axiom_refusal(reported, name) is None else "partial"
```

  In the builder's `lean_check`: after `check`, when `node_id` was given, `published, verdict = await publish(node, source, result, k)` and return `{**result, "published": published, "local_compile": await local_compile(node, source, result, verdict, k), "claimed": claim(node["id"], k)}`. `publish` runs `_publication_refusal`; when the file is complete and the node has a statement it calls `verify_statement` once (fatal codes re-raise; another `HarnessError` becomes `{"ok": False, "reason": error.code, "axioms": None}`); computes `_source_rank`; a `None` rank returns `{"recorded": False, "module", "reason": verdict["reason"]}`; otherwise it creates the artifact (`ArtifactCreate(experiment_id, branch_id, kind="lean_source", content=source, provenance={"node_id", "module"})`, key `f"{k}:source"`) and returns `_soft(lambda: service.record_lean_source(node["id"], artifact["id"], record, agent, f"{k}:publish"))`. `local_compile` keeps its checks but uses the passed verdict (no second `verify_statement`; `None` → reason `statement_check_not_run`). `claim` replaces `renew_claim`: `service.claim_node(node_id, "claim", agent, f"{key}:claim")`, returning `False` on a non-fatal `HarnessError`. Update tests that read `claim_renewed` to `claimed`. `commons_query` gains `"source": choice(("verified", "complete", "partial", "stub", "none"), "Only nodes whose source has this rank.", nullable=True)` (default `None`).
- [ ] **Step 6: Referee reads; the notebook's candidate skips node modules.** `referee_may_read_artifact`: return `True` when `artifact_id == (node.get("lean_source") or {}).get("artifact_id")`, before the thread scan. `memory.py` `working_context`'s `source_rows` query (picking the branch's newest `lean_source` artifact as `active_source`): raise its `.limit(1)` to `.limit(20)` and, in Python, take the first row whose `payload.get("provenance") or {}` has no `"node_id"` (a node module published by `lean_check(node_id=...)` is that node's lemma, not the branch's own submission candidate). Add to `tests/test_memory.py`: `test_working_context_skips_node_modules_for_the_active_source_candidate` — a branch that first publishes a `lean_source` on a `commons_node` (`provenance={"node_id": ..., "module": ...}`, newer `created_at`) and then creates a plain `lean_source` artifact with no `node_id` (older): `working_context(...)["readable_work"]["active_source"]["reference"]` points at the plain artifact, not the node module.
- [ ] **Step 7: Docs.** `docs/RESEARCH_NETWORK.md`, new "Lemma store" bullet: a clean `lean_check` with `node_id` publishes the file as the node's module `Commons.N<8 hex>`, ranked `verified` (the statement check passed with standard axioms), `complete` (no `sorry`, the check could not judge) or `partial`; higher ranks replace lower ones, a verified source only by its publisher or the author; publishing claims the node; imports become `depends_on` edges.
- [ ] **Step 8: Run the tests**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_commons_sources.py tests/test_society_tools.py tests/test_statement_check.py tests/test_commons.py tests/test_commons_review.py tests/test_society_simulation.py tests/test_id_prefixes.py tests/test_memory.py -q`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add src/physharness/commons_sources.py src/physharness/service.py src/physharness/commons.py src/physharness/commons_review.py src/physharness/orchestration/society_tools.py src/physharness/memory.py docs/RESEARCH_NETWORK.md tests/test_commons_sources.py tests/test_society_tools.py tests/test_memory.py
git -c user.name=Kieran -c user.email=88352982+zubadestroyer1@users.noreply.github.com commit -m "feat: publish checked Lean as ranked node modules in a shared lemma store" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 10: `import Commons.N…` in `lean_check` and one flattened file for the verifier (#12b)

**Files:**
- Modify: `src/physharness/commons_sources.py` (pure inliner; `CommonsSourceMixin._module`, `expand_commons`)
- Modify: `src/physharness/orchestration/society_tools.py:619-731` (both `lean_check`s expand; `publish` records imports), `:1352-1368` (`submit_for_verification`)
- Modify: `src/physharness/acceptance.py` (`verify_candidate` gains an internal-only `commons_modules=None` keyword: not part of the API/MCP request body, so only the flattening step below can set it; stored verbatim on the receipt payload)
- Modify: `docs/RESEARCH_NETWORK.md` (Lemma store bullet), `docs/FORMAL_ENVIRONMENT.md` (candidate section: flattened submissions)
- Test: `tests/test_commons_sources.py`, `tests/test_society_tools.py`

**Interfaces:**
- Consumes: `CommonsSourceMixin._module_node`, `node_module`, `COMPLETE_RANKS` (Task 9); `lean_code` (`lean_session.py:336`); `MAX_CANDIDATE_CHARACTERS` (`verification/boundary.py:28`).
- Security note (ruling on node acceptance, Task 12): `ArtifactCreate.provenance` is caller-writable free-form data (`service.py:622`, "Free-form provenance is not authority") and reachable from the plain API/MCP `create_artifact`; Task 12's node acceptance must never treat `artifact.provenance.commons` as authority. This task's `verify_candidate(experiment_id, artifact_id, publication, actor, key, *, commons_modules=None)` adds that keyword; `api.py`'s `POST /v1/experiments/{identifier}/verify` endpoint (`VerifyInput` body) does not accept it, so it can be set only by this task's own internal call inside `submit_for_verification`, from the genuinely platform-resolved `expansion.modules` (each entry's `sha256` and `node_id` come from live node lookups in `_module`, never from caller JSON). The receipt payload gains `commons_modules: [{"module", "node_id", "sha256", "branch_id"}]` (empty/absent for anything verified outside this flattening path). Task 12's `_commons_goal_accepted` reads this field, never the artifact's `provenance`.
- Produces: `commons_sources.COMMONS_IMPORT`, `MAX_COMMONS_MODULES = 200`; dataclasses `Module(name, node_id, source, rank, sha256=None, artifact_id=None, branch_id=None)` and `Expansion(source, modules=(), segments=(), closure_complete=True, stubs=())` (`segments` are `(first_line, last_line, module_or_None, origin_line)`); `split_imports(source) -> (modules, env_lines, rest_lines, first_rest_index)`; `scope_closers(module, source) -> list[str]`; `inline_commons(source, resolve, *, max_bytes) -> Expansion`; `remap(result, expansion) -> dict`; `CommonsSourceMixin.expand_commons(experiment_id, source, actor, *, max_bytes) -> Expansion` (Tasks 11 and 14). Errors: `COMMONS_IMPORT_CYCLE`, `COMMONS_EXPANSION_LIMIT`, `COMMONS_MODULE_REFUSED`, `COMMONS_MODULE_NOT_FOUND`, `COMMONS_EXPANSION_TOO_LARGE`, `COMMONS_CLOSURE_INCOMPLETE` (all 422 but not-found 404). `lean_check` results gain `commons: {"modules", "closure_complete", "stubs"}` when the file imports modules; `submit_for_verification` results gain `expanded_artifact_id` and `commons_modules`.

- [ ] **Step 1: Write the failing tests** (`tests/test_commons_sources.py`):

```python
A, B = "Commons.Naaaaaaaa", "Commons.Nbbbbbbbb"

def module(name, source, rank="verified"):
    stub = rank == "stub"
    return Module(name, name[-8:] + "-node", source, rank, None if stub else "s" * 64, None if stub else "art", "b")

def resolver(*modules):
    table = {m.name: m for m in modules}

    def resolve(name):
        if name not in table:
            raise HarnessError("COMMONS_MODULE_NOT_FOUND", name, status=404)
        return table[name]

    return resolve

def test_source_without_commons_imports_is_returned_unchanged():
    text = "import Mathlib\n\ntheorem t : True := trivial\n"
    assert inline_commons(text, resolver(), max_bytes=30_000) == Expansion(text)

def test_imports_are_hoisted_and_modules_ordered_by_dependency():
    a = module(A, "import Mathlib.Data.Nat.Basic\n\ntheorem a : 1 = 1 := rfl\n")
    b = module(B, f"import Mathlib\nimport {A}\n\ntheorem b : 1 = 1 := a\n")
    flat = inline_commons(f"import {B}\nimport Mathlib\nopen Nat\n\ntheorem c : 1 = 1 := b\n",
                          resolver(a, b), max_bytes=30_000)
    lines = flat.source.split("\n")
    assert lines[:2] == ["import Mathlib", "import Mathlib.Data.Nat.Basic"]
    assert [m.name for m in flat.modules] == [A, B] and "import Commons" not in flat.source
    assert flat.source.index("theorem a") < flat.source.index("theorem b") < flat.source.index("theorem c")
    caller = remap({"messages": [{"line": lines.index("theorem c : 1 = 1 := b") + 1}], "holes": []}, flat)
    assert caller["messages"][0]["line"] == 5

def test_each_module_is_sectioned_and_its_open_namespace_closed():
    a = module(A, "import Mathlib\nopen Nat\nnamespace Foo\n\ntheorem a : 1 = 1 := rfl\n")
    lines = inline_commons(f"import {A}\n\ntheorem c : 1 = 1 := Foo.a\n", resolver(a),
                           max_bytes=30_000).source.split("\n")
    start = lines.index("section")
    assert lines[start + 2] == "open Nat" and lines[lines.index("end Foo") + 1] == "end"

def test_cycles_exit_unbalanced_scopes_stubs_and_size_are_handled():
    loop = resolver(module(A, f"import {B}\n"), module(B, f"import {A}\n"))
    with pytest.raises(HarnessError, match="imports itself"):
        inline_commons(f"import {A}\n", loop, max_bytes=30_000)
    for text in ("theorem a : True := trivial\n#exit\n", "theorem a : True := trivial\nend Foo\n"):
        with pytest.raises(HarnessError) as refused:
            inline_commons(f"import {A}\n", resolver(module(A, text)), max_bytes=30_000)
        assert refused.value.code == "COMMONS_MODULE_REFUSED"
    stub = module(A, "import Mathlib\n\ntheorem a : 1 = 1 := sorry\n", rank="stub")
    flat = inline_commons(f"import {A}\n", resolver(stub), max_bytes=30_000)
    assert flat.closure_complete is False and flat.stubs == (stub.node_id,)
    with pytest.raises(HarnessError) as big:
        inline_commons(f"import {A}\n", resolver(stub), max_bytes=10)
    assert big.value.code == "COMMONS_EXPANSION_TOO_LARGE"
```

  `tests/test_society_tools.py` (specified; build them on Task 9's test): `test_peer_import_expands_and_records_a_depends_on_edge` — alpha publishes `trace_add` on node L; beta's `lean_check` of `f"import {module}\n\ntheorem uses : (1 : Nat) + 1 = 2 := trace_add\n"` with `node_id` M: `workspace.lean.sources[-1]` contains `theorem trace_add` and no `import Commons`; `checked["commons"] == {"modules": [module], "closure_complete": True, "stubs": []}`; `read_node(M)["edges_out"]` has `depends_on` L. `test_submit_with_commons_imports_verifies_one_flattened_artifact` — a `FakeWorkspace` subclass whose `read` returns `{"text": text}` and whose `store_workspace_artifact(arguments, operation_id, agent)` creates a real `lean_source` artifact through the service; the result's `expanded_artifact_id` artifact has `provenance["commons"][0]["module"] == module` and a queued receipt exists for it. `test_submit_refuses_an_incomplete_closure` — importing a stub gives `COMMONS_CLOSURE_INCOMPLETE` listing it.
- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_commons_sources.py tests/test_society_tools.py -q -k "inline or hoisted or sectioned or cycles or unchanged or peer_import or flattened or incomplete_closure"`
Expected: FAIL (`inline_commons` does not exist).

- [ ] **Step 3: The inliner** (`commons_sources.py`; imports `re`, `dataclass`, `lean_code`):

```python
COMMONS_IMPORT = re.compile(r"Commons\.N[0-9a-f]{8}(?:[0-9a-f]{4}){0,2}")
MAX_COMMONS_MODULES = 200
_SCOPE = re.compile(r"(?<![\w.'!?])(namespace|section|mutual|end)(?![\w'!?])")
_SCOPE_NAME = re.compile(r"[ \t]+([\w.'!?]+)")

def split_imports(source):
    """(commons modules, environment import lines, the lines from the first non-import
    line on, that line's 0-based index). Blank and `--` lines before it are skipped."""
    lines, modules, env = source.split("\n"), [], []
    for index, line in enumerate(lines):
        code = line.split("--", 1)[0].strip()
        if not code:
            continue
        if not code.startswith("import "):
            return modules, env, lines[index:], index
        names = code.split()[1:]
        modules += [n for n in names if COMMONS_IMPORT.fullmatch(n) and n not in modules]
        others = [n for n in names if not COMMONS_IMPORT.fullmatch(n)]
        if others:
            env.append("import " + " ".join(others))
    return modules, env, [], len(lines)

def scope_closers(name, source):
    """`end` lines for the scopes a module leaves open; refuses an `end` it never opened."""
    code, stack = lean_code(source), []
    for match in _SCOPE.finditer(code):
        label = _SCOPE_NAME.match(code, match.end())
        if match.group(1) == "end":
            if not stack:
                raise HarnessError("COMMONS_MODULE_REFUSED", f"{name} closes a scope it never opened.", status=422, details={"module": name})
            stack.pop()
        else:
            stack.append(label.group(1) if label and match.group(1) != "mutual" else "")
    return [f"end {label}".rstrip() for label in reversed(stack)]

def inline_commons(source, resolve, *, max_bytes):
    """Flatten `import Commons.N…` into one self-contained file (S1 audit #12): environment
    imports hoisted once, each module in dependency order inside its own section, then the
    caller's lines. A source without commons imports is returned unchanged."""
    if not split_imports(source)[0]:
        return Expansion(source)
    ordered, active, done = [], [], set()

    def visit(name):
        if name in done:
            return
        if name in active:
            raise HarnessError("COMMONS_IMPORT_CYCLE", f"{name} imports itself through {', '.join(active)}.", status=422, details={"modules": [*active, name]})
        if len(done) + len(active) >= MAX_COMMONS_MODULES:
            raise HarnessError("COMMONS_EXPANSION_LIMIT", f"A closure inlines at most {MAX_COMMONS_MODULES} modules.", status=422)
        active.append(name)
        found = resolve(name)
        if "#exit" in found.source:
            raise HarnessError("COMMONS_MODULE_REFUSED", f"{name} contains #exit.", status=422, details={"module": name})
        for child in split_imports(found.source)[0]:
            visit(child)
        active.pop()
        done.add(name)
        ordered.append(found)

    for name in split_imports(source)[0]:
        visit(name)
    out = []
    for text in (source, *(m.source for m in ordered)):
        out += [line for line in split_imports(text)[1] if line not in out]
    segments = []
    for found in ordered:
        label = f"-- {found.name}: node {found.node_id}, {found.rank}"
        block = ["section", label, *split_imports(found.source)[2], *scope_closers(found.name, found.source), "end"]
        segments.append((len(out) + 1, len(out) + len(block), found.name, 1))
        out += block
    _, _, rest, first = split_imports(source)
    segments.append((len(out) + 1, len(out) + len(rest), None, first + 1))
    flat = "\n".join(out + rest)
    size = len(flat.encode("utf-8"))
    if size > max_bytes:
        raise HarnessError(
            "COMMONS_EXPANSION_TOO_LARGE", f"The flattened file is {size:,} bytes; the limit here is {max_bytes:,}.",
            status=422, details={"bytes": size, "limit": max_bytes},
            remediation="Write it with commons_fetch(expand_path=…) and check it with lake env lean in the shell.",
        )
    return Expansion(flat, tuple(ordered), tuple(segments),
                     all(m.rank in COMPLETE_RANKS for m in ordered),
                     tuple(m.node_id for m in ordered if m.rank == "stub"))
```

  `remap(result, expansion)` returns `result` unchanged without modules; otherwise each message and hole whose `line` falls in a segment `(first, last, module, origin)` gets `line = origin + line - first` for the caller's segment, or `{"line": None, "module": module, "expanded_line": line}` for a module's. (Wrap the long lines for ruff.) The mixin's `_module(session, name, actor, experiment_id) -> Module` resolves `_module_node`; with a `lean_source` it reads the text with `self.artifacts.get(source["sha256"]).decode("utf-8")` and reports the effective rank (a `verified` source for an older statement counts as `complete`); with an elaborated Lean statement and no source it returns the stub `f"{header}\n\ntheorem {name} {statement} := sorry\n"` with rank `stub`; otherwise `COMMONS_MODULE_NOT_FOUND` ("has no published source and no elaborated Lean statement"). `expand_commons` opens one session and calls `inline_commons(source, lambda name: self._module(session, name, actor, experiment_id), max_bytes=max_bytes)`.
- [ ] **Step 4: `lean_check` expands.** Both declarations check `expansion = service.expand_commons(experiment_id, a["source"], agent, max_bytes=MAX_SOURCE)`'s source, return `remap(checked, expansion)`, and add `commons` when `expansion.modules`. `publish` passes `expansion.source` to `verify_statement`, keeps `statement_found` and the artifact content on the caller's own text, adds `"unbalanced_scopes"` to `_publication_refusal` (when `scope_closers` raises for the caller's text), and records `imports` as the caller's direct imports: `[{"module": name, "node_id": by_name[name].node_id, "sha256": by_name[name].sha256} for name in split_imports(source)[0]]`. Add one sentence to the builder's description: "`import Commons.N…` pulls in published node modules (a node with only a Lean statement imports as a sorry stub)."
- [ ] **Step 5: Flattened submission.** `submit_for_verification`: read the first 64 KiB with `workspace_tools.read({"path": a["path"], "offset": 0, "length": 65536}, f"{k}:peek")`; without commons imports in `peek.get("text", "")` call `submit_workspace_candidate` exactly as today. Otherwise: `promoted = await workspace_tools.store_workspace_artifact({"path", "sha256", "target_digest"}, k + ":capture", agent)`; `source = service.artifact_content(promoted["artifact_id"], agent).decode("utf-8")`; `expansion = service.expand_commons(experiment_id, source, agent, max_bytes=MAX_CANDIDATE_CHARACTERS)`; if `not expansion.closure_complete` raise `COMMONS_CLOSURE_INCOMPLETE` with `details={"modules": [{"module", "rank"} of each non-complete module]}` and remediation "Publish complete sources for these modules first; the verifier rejects sorry."; create `ArtifactCreate(experiment_id, branch_id, kind="lean_source", content=expansion.source, provenance={"expanded_from": promoted["artifact_id"], "commons": [{"module", "node_id", "artifact_id", "sha256", "branch_id", "chars": len(m.source)} per module]})` with key `f"{k}:flatten"` (this `provenance.commons` is descriptive only, read by Task 11's metrics; it is never treated as authority — see the security note above); `receipt = service.verify_candidate(experiment_id, flat["id"], True, agent, f"{k}:verification", commons_modules=[{"module": m.name, "node_id": m.node_id, "sha256": m.sha256, "branch_id": m.branch_id} for m in expansion.modules])`; return `{"artifact_id": promoted["artifact_id"], "expanded_artifact_id": flat["id"], "candidate_sha256": flat["sha256"], "commons_modules": [...], "receipt_id": receipt["id"], "status": receipt["status"]}`. `verify_candidate` stores its `commons_modules` keyword verbatim as `receipt.payload["commons_modules"]` (`[]` when not given); the API's request body has no such field, so a caller submitting through `POST /v1/experiments/{identifier}/verify` always gets `[]` there regardless of the artifact's own `provenance`.
- [ ] **Step 6: Docs.** Lemma store bullet: imports, stubs, the flattened submission (the verifier still checks one `Solution.lean`; its provenance lists the inlined modules). `docs/FORMAL_ENVIRONMENT.md`: one sentence that a society submission importing commons modules is flattened by the platform before verification.
- [ ] **Step 7: Run the tests**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_commons_sources.py tests/test_society_tools.py tests/test_society_simulation.py tests/test_statement_check.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/physharness/commons_sources.py src/physharness/orchestration/society_tools.py docs/RESEARCH_NETWORK.md docs/FORMAL_ENVIRONMENT.md tests/test_commons_sources.py tests/test_society_tools.py
git -c user.name=Kieran -c user.email=88352982+zubadestroyer1@users.noreply.github.com commit -m "feat: inline commons imports for lean_check and flatten submissions for the verifier" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 11: `commons_fetch`, private workspaces, and reuse by provenance (#12c)

**Files:**
- Modify: `src/physharness/commons_sources.py` (`commons_module(node_id, actor) -> dict`)
- Modify: `src/physharness/orchestration/society_tools.py:67-94` (`SOCIETY_TOOL_NAMES`: `commons_fetch` right after `commons_claim`, matching its registration order), `:558-598` (privacy sentence in `shell`, `read_file`, `write_file`), after `commons_claim` (`:1186-1195`: the `commons_fetch` tool); `society_prompt.py:13-21` (`NORMS`)
- Modify: `tools/society_metrics.py:46-60` (bucket); add the new `_source_provenance` function beside `compute_metrics` (`:421-500`, which it does not replace) and merge its result into `compute_metrics`'s return
- Modify: `work/society-s1/RUN_PLAN.md` §7 (reuse row), `docs/RESEARCH_NETWORK.md` (tool table, Lemma store bullet)
- Test: `tests/test_society_tools.py:442-470`, new tests; `tests/test_society_metrics.py`; `tests/test_society_scaffolding.py` (NORMS)

**Interfaces:**
- Consumes: `expand_commons`, `CommonsSourceMixin._module` (Task 10), `ident` (Task 4).
- Produces: tool `commons_fetch(node_ids: list[str] = [], expand_path: str | None = None)` returning `{"fetched": [{"node_id", "module", "rank", "sha256", "path"}]}` (files at `Commons/N<hex>.lean`) or `{"path", "sha256", "modules", "closure_complete", "stubs"}` (file `<stem>.flat.lean`); `society_metrics._source_provenance(nodes, artifacts, receipt) -> dict` with keys `nodes_by_source`, `cross_branch_imports`, `accepted_proof_modules`, `accepted_proof_cross_branch_modules`, `accepted_proof_cross_branch_char_share` (the last three `None` when the accepted candidate has no commons provenance).

- [ ] **Step 1: Write the failing tests**

`tests/test_society_metrics.py`:

```python
def test_source_provenance_counts_cross_branch_reuse():
    nodes = [
        {"id": "n1", "lean_source": {"rank": "verified", "branch_id": "b1", "imports": []}},
        {"id": "n2", "lean_source": {"rank": "complete", "branch_id": "b2",
                                     "imports": [{"module": "Commons.Nn1", "node_id": "n1", "sha256": "x"}]}},
        {"id": "n3", "lean_elaborated": True, "lean_name": "t", "lean_statement": ": True"},
        {"id": "n4"},
    ]
    commons = [{"module": "Commons.Nn1", "node_id": "n1", "branch_id": "b1", "chars": 300},
               {"module": "Commons.Nn2", "node_id": "n2", "branch_id": "b2", "chars": 100}]
    artifacts = [{"id": "flat", "branch_id": "b2", "provenance": {"commons": commons}}]
    result = metrics_tool._source_provenance(nodes, artifacts, {"artifact_id": "flat"})
    assert result["nodes_by_source"] == {"complete": 1, "none": 1, "stub": 1, "verified": 1}
    assert result["cross_branch_imports"] == 1
    assert result["accepted_proof_modules"] == 2
    assert result["accepted_proof_cross_branch_modules"] == 1
    assert result["accepted_proof_cross_branch_char_share"] == 0.75
    legacy = metrics_tool._source_provenance([{"id": "n"}], [], None)
    assert legacy["accepted_proof_modules"] is None and legacy["nodes_by_source"] == {"none": 1}
```

`tests/test_society_tools.py`:

```python
async def test_commons_fetch_writes_modules_and_a_flat_file(lab):
    service, author, exp, _, (alpha, _) = society_lab(lab)
    agent, context = running(service, author, exp, alpha.branch_id)
    workspace = FakeWorkspace()
    tools = profile(service, agent, context, workspace=workspace)
    created = await call(tools, "commons_node", lemma_args())
    await call(tools, "commons_node", {"action": "set_lean_statement", "node_id": created["id"], **LEAN})
    fetched = await call(tools, "commons_fetch", {"node_ids": [created["id"][:8]]})
    [entry] = fetched["fetched"]
    assert entry["rank"] == "stub" and entry["path"] == "Commons/N" + created["id"][:8] + ".lean"
    [write] = [args for name, args in workspace.calls if name == "write"]
    assert write["content"].endswith("theorem trace_add : (1 : Nat) + 1 = 2 := sorry\n")
    for description in ("shell", "read_file", "write_file"):
        assert "Your workspace is private" in definition(widest(), description)["description"]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_society_metrics.py tests/test_society_tools.py -q -k "provenance or commons_fetch"`
Expected: FAIL.

- [ ] **Step 3: Implement**
  - `commons_module(node_id, actor)`: scope the node with `_get`, derive `node_module`, return `{"node_id", "module", "source", "rank", "sha256"}` from `self._module(...)`.
  - Tool (registered right after `commons_claim`, inside `if workspace_tools is not None:`):
    - schema `{"node_ids": array(ident("A commons node.", ("commons_node",)), 20, "Nodes whose modules to write to Commons/N….lean."), "expand_path": text(PATH, "A workspace .lean file whose Commons imports to inline into <stem>.flat.lean.", nullable=True)}`, defaults `{"node_ids": [], "expand_path": None}`;
    - exactly one of the two, else `invalid("Supply node_ids or expand_path.")`;
    - `node_ids`: write each module's text to `"Commons/" + module.split(".", 1)[1] + ".lean"` with key `f"{k}:write-{index}"`;
    - `expand_path`: read the file in 64 KiB pages with `workspace_tools.read` until `result.get("remaining_bytes", 0) == 0` (text from `result.get("text", "")`) (at most `MAX_CANDIDATE_CHARACTERS` bytes, else `COMMONS_EXPANSION_TOO_LARGE`), expand with `max_bytes=MAX_CANDIDATE_CHARACTERS`, write `removesuffix(".lean") + ".flat.lean"` (refuse with `invalid(...)` past an E2B per-file limit from `_write_limit_bytes`);
    - description: "Bring commons Lean into your private workspace: node_ids writes each node's module (or its sorry stub) to Commons/N….lean; expand_path writes <file>.flat.lean with every `import Commons.N…` inlined, for `lake env lean` in the shell (no 30,000-byte bound)."
  - Privacy sentence appended to the `shell`, `read_file` and `write_file` descriptions: " Your workspace is private: no other agent can read it. Share Lean by publishing it on its node (lean_check with node_id); others import it as `import Commons.N…`."
  - `NORMS`: append (do not insert by index; later tasks edit earlier norms by matching their text) `"Publish Lean on its node (lean_check with node_id) and import peers' modules instead of copying their code."` at the end of the tuple.
  - Metrics: add `"commons_fetch"` to `COMMONS_SOCIETY`; add `_source_provenance` (counts by `source_state`-equivalent logic on export dicts: `lean_source.rank`, else `"stub"` when `lean_elaborated`, else `"none"`; `cross_branch_imports` counts `imports` whose target node's `lean_source.branch_id` differs from the importer's; the accepted-proof figures come from `receipt["artifact_id"]`'s artifact `provenance.commons`, comparing each entry's `branch_id` with that artifact's `branch_id`, and the char share is cross-branch `chars` over all module `chars`, rounded to 4 places) and merge `**_source_provenance(nodes, records.get("artifact", []), receipt)` into `compute_metrics`.
  - `test_society_catalog_widest`: replace the literal count line with `assert len(names(dispatcher)) == len(SOCIETY_TOOL_NAMES) - 1 and len(REFEREE_TOOLS) == len(REFEREE_TOOL_NAMES)` (import `REFEREE_TOOL_NAMES`); Task 21 restores literal counts. Update the NORMS copy in `tests/test_society_scaffolding.py`.
- [ ] **Step 4: Docs.** `RUN_PLAN.md` §7 "Citation and reuse rate" row adds the new metric names. `docs/RESEARCH_NETWORK.md`: `commons_fetch` in the tool table's Commons row; the workspace-privacy sentence in the Lemma store bullet.
- [ ] **Step 5: Run the tests**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_society_metrics.py tests/test_society_tools.py tests/test_society_scaffolding.py tests/test_society_simulation.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/physharness/commons_sources.py src/physharness/orchestration/society_tools.py src/physharness/orchestration/society_prompt.py tools/society_metrics.py work/society-s1/RUN_PLAN.md docs/RESEARCH_NETWORK.md tests/test_society_metrics.py tests/test_society_tools.py tests/test_society_scaffolding.py
git -c user.name=Kieran -c user.email=88352982+zubadestroyer1@users.noreply.github.com commit -m "feat: add commons_fetch, state workspace privacy, and measure reuse by provenance" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 12: Drop the status ladder and fidelity reviews; the verifier accepts imported nodes (#17)

**Files:**
- Modify: `src/physharness/commons_models.py:24-59` (statuses, transitions, `public_status`)
- Modify: `src/physharness/commons.py:231-233,324-325` (create `open`), `:459-472` (`_node_summaries`: public status and `source`), `:477-521` (`read_node`: public status; `rests_on` by source), `:597-605`, `:607-641`, `:643-709` (public status; `status="open"` matches legacy values), `:754-794` (`_set_node_status(..., announce=True)`)
- Modify: `src/physharness/commons_review.py`: delete `FORMAL_STATUSES` (`:33`), the fidelity entries of `REVIEW_VERDICTS`-driven objectives (`:51-60`, `:73-91`), `MAX_FIDELITY_REVIEWS` and its panel block (`:45`, `:412-430`), `_claimant_families` (`:536-560`), `_standing_veto` (`:511-522`), `_review_tally`, `_refereed_evidence`, `_formally_stated_evidence` (`:776-841`), `_apply_review` (`:877-911`), the demotion in `set_lean_statement` (`:1126-1140`), `record_local_compile` with `_CompileResult`/`_LocalCompile` (`:277-296`, `:1150-1226`); change `_review_precondition` (`:320-338`), `_statement_owner` (`:441-509`), `request_review` (`:603-715`), `submit_review` (`:913-1004`), `_may_formalize` (`:1006-1029`), `set_lean_statement` (result `dependents`), `_commons_goal_accepted` (`:1229-1256`)
- Modify: `src/physharness/orchestration/society_tools.py` (`STATUSES` choice, `_node_view`, `commons_node` `request_review` without `scope`, delete `local_compile` and its result key, `_recruit_objective` status), `society_prompt.py` (the "Ask for a referee…" norm, matched by text; playbook step 4)
- Modify: `docs/RESEARCH_NETWORK.md:120-210` (Status and Referees), `docs/IMPLEMENTATION_STATUS.md:19-36,85`, `docs/FORMAL_ENVIRONMENT.md:172`, `PLAN.md` §2.2, §3.1 (norms), §3.7 (playbook), §5.2
- Test: `tests/commons_helpers.py:58-72`, `tests/test_commons_review.py`, `tests/test_commons.py:377-440`, `tests/test_society_tools.py`, `tests/test_statement_check.py:145-182`, `tests/test_society_scaffolding.py`, `tests/test_society_simulation.py`, and every `request_review(…, "informal", …)` call (`grep -rn 'request_review(' tests`)

**Interfaces:**
- Consumes: `lean_source`, `source_state`, `COMPLETE_RANKS`, `MAX_COMMONS_MODULES` (Tasks 9–10).
- Produces: `STATUSES = ("open", "accepted", "refuted", "abandoned")`, `LEGACY_OPEN_STATUSES = ("informal", "refereed", "formally_stated", "compiles_locally")`, `public_status(status: str) -> str`; `request_review(node_id, actor, key) -> dict` (no scope; stored scope `informal`, the plan review); error `REVIEW_UNNEEDED`; `set_lean_statement` result gains `dependents: int`; `_set_node_status(session, row, status, *, reason, evidence, op, announce=True)`. `lean_check` results no longer carry `local_compile`.

- [ ] **Step 1: Write the failing tests** (`tests/test_commons_review.py`; `publish` as in Task 9's tests, moved to `tests/commons_helpers.py` so both files import it)

```python
def test_nodes_are_open_and_legacy_statuses_read_as_open(lab):
    service, _, exp, _, (alpha, _) = society_lab(lab)
    goal = service.query_nodes(exp["id"], alpha, node_type="goal")["items"][0]
    node = service.create_node(exp["id"], lemma(), alpha, "lemma")
    assert goal["status"] == "open" and node["status"] == "open"
    with service.db.transaction() as session:
        row = session.get(RecordRow, node["id"])
        row.payload = {**row.payload, "status": "formally_stated"}  # an S1 record
    assert service.read_node(node["id"], alpha)["node"]["status"] == "open"
    assert node["id"] in {i["id"] for i in service.query_nodes(exp["id"], alpha, status="open")["items"]}
    set_status(service, node["id"], "accepted")
    assert service.read_node(node["id"], alpha)["node"]["status"] == "accepted"

def test_a_review_records_its_verdict_and_moves_nothing(lab):
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    node = service.create_node(exp["id"], lemma(), alpha, "lemma")
    requested = service.request_review(node["id"], beta, "review")
    submitted = submit(service, requested, exp, "wrong", objections=["Step 2 fails."])
    assert submitted["node_status"] == "open" and submitted["objection_post_id"]
    publish(service, node["id"], alpha, "complete", "src")
    with pytest.raises(HarnessError) as unneeded:
        service.request_review(node["id"], beta, "again")
    assert unneeded.value.code == "REVIEW_UNNEEDED"

def test_a_verified_proof_accepts_the_nodes_it_imports(lab):
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    used = service.create_node(exp["id"], lemma(), alpha, "used")
    published = publish(service, used["id"], alpha, "complete", "used-src")
    source = service.read_node(used["id"], alpha)["node"]["lean_source"]
    stale = service.create_node(exp["id"], lemma("Other"), beta, "stale")
    commons = [
        {"module": published["module"], "node_id": used["id"], "sha256": source["sha256"],
         "branch_id": alpha.branch_id, "chars": 40},
        {"module": "Commons.Nffffffff", "node_id": stale["id"], "sha256": "0" * 64,
         "branch_id": beta.branch_id, "chars": 1},
    ]
    flat = service.create_artifact(
        ArtifactCreate(experiment_id=exp["id"], branch_id=beta.branch_id, kind="lean_source",
                       content="flattened proof", provenance={"commons": commons}),
        beta, "flat",
    )
    service.verifier = Checker()
    receipt = service.verify_candidate(exp["id"], flat["id"], False, beta, "verify-flat")
    operator = Principal(id="test-checker", project_id="lab", role="operator")
    assert service.process_verification(receipt["id"], operator)["status"] == "verified"
    assert service.read_node(used["id"], alpha)["node"]["status"] == "accepted"
    assert service.read_node(stale["id"], alpha)["node"]["status"] == "open"
```

  Also (specified): `test_set_lean_statement_never_moves_status_and_reports_dependents` (a node another node imports: `dependents == 1`, status unchanged); `test_only_the_author_changes_a_statement_with_a_verified_source` (a claimant gets `NODE_AUTHORITY`); `test_rests_on_counts_sources` (replaces `tests/test_commons.py::test_rests_on_counts_dependency_statuses`: counts keyed `verified`/`complete`/`partial`/`stub`/`none`, `conditional` true while any dependency is below `complete`); `test_forged_artifact_provenance_does_not_accept_unused_nodes` (security, F8: build the accepted-proof scenario as in `test_a_verified_proof_accepts_the_nodes_it_imported`, but create the `flat` artifact with a forged `provenance={"commons": commons}` naming `used["id"]` with its real, matching `lean_source.sha256` — and call `service.verify_candidate(exp["id"], flat["id"], False, beta, "verify-flat")` directly, with no `commons_modules`, exactly as `api.py`'s verify endpoint would; after `process_verification` accepts the goal, `used["id"]`'s status stays `open` — the forged, caller-writable `provenance.commons` is never read for acceptance, only a receipt's own `commons_modules`).
- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_commons_review.py -q -k "legacy_statuses or moves_nothing or accepts_the_nodes"`
Expected: FAIL.

- [ ] **Step 3: Statuses** (`commons_models.py`):

```python
STATUSES = ("open", "accepted", "refuted", "abandoned")
# Ladder values stored before the S1 remediation; every reader treats them as open.
LEGACY_OPEN_STATUSES = ("informal", "refereed", "formally_stated", "compiles_locally")
CLOSED_STATUSES = frozenset({"accepted", "refuted", "abandoned"})
# Only author abandonment and platform acceptance or refutation move a node (S1 audit #17).
ALLOWED_TRANSITIONS = {
    **{status: {"accepted", "refuted", "abandoned"} for status in ("open", *LEGACY_OPEN_STATUSES)},
    **{status: set() for status in CLOSED_STATUSES},
}

def public_status(status):
    return "open" if status in LEGACY_OPEN_STATUSES else status
```

- [ ] **Step 4: Commons reads.** Goal and new nodes are created `open` (`status_reason` "reviewed target"/"proposed"). Every read view (`_node_summaries`, `read_node`'s node and edges, `_node_item`, `_frontier`, `_goal_view` inputs) shows `public_status`; exports keep raw values. `query_nodes(status=…)` accepts `STATUSES` and compares `public_status(node["status"])`. `_node_summaries` adds `"source": source_state(payload)`. `read_node.rests_on` becomes `{"counts": Counter(source of each rests_on node), "conditional": truncated or any(source not in COMPLETE_RANKS), "truncated": truncated}`. `_set_node_status` gains `announce=True` and calls `_node_hooks_after_status` only when it is true.
- [ ] **Step 5: Reviews** (`commons_review.py`). Delete the items listed under Files. `_review_precondition(node)`: the node must be open (public status) and of type `approach`, `conjecture` or `lemma` (else `REVIEW_PRECONDITION`); when `source_state(node) in COMPLETE_RANKS` raise `HarnessError("REVIEW_UNNEEDED", "A compiled node needs no referee; the verifier checks it.", remediation="Build on it, or ask a referee about a plan (an approach or skeleton) instead.")`. `request_review(node_id, actor, key)` uses scope `"informal"` internally, drops the veto and fidelity branches, and passes the node's direct imports as an interface to `referee_objective`: `interface=[f"{entry['module']}: theorem {n['lean_name']} {n['lean_statement']}" for each import whose node has a statement][:20]`; `referee_objective(scope, node_id, node, interface=None)` puts `interface` into the fenced data when given and its preamble reads "judge whether the plan or argument is sound and complete …; the data may list the Lean interface the plan imports (statements, no proofs)". `submit_review` records the verdict and the objection post and returns `node_status: public_status(...)`; nothing moves. Keep `REVIEW_VERDICTS["fidelity"]` only so a stored fidelity task can still submit. `_may_formalize`: the author always; a live claimant sets a missing, non-elaborating or own statement, unless the node has a `verified` source for its current statement (then author only). `set_lean_statement` drops the demotion and returns `dependents` = the count of `depends_on` edges into the node. `_commons_goal_accepted`: after accepting the goal, read `(receipt.payload.get("commons_modules") or [])[:MAX_COMMONS_MODULES]` — the field Task 10's `verify_candidate` alone writes, never the candidate artifact's `provenance` (caller-writable, never authority: a forged `provenance.commons` on the artifact must not accept anything); for each entry whose node is in the experiment, open, and has `lean_source.sha256 == entry["sha256"]`, call `_set_node_status(session, node, "accepted", reason="in an independently verified proof", evidence={"receipt_id": receipt_id, "source_sha256": entry["sha256"]}, op=op, announce=False)`.
- [ ] **Step 6: Tools and prompt.** `commons_query.status` choices = new `STATUSES`; `_node_view` public status; `commons_node`: drop the `scope` property, `ACTION_FIELDS["request_review"] = {"node_id"}`, `ACTION_REQUIRED["request_review"] = ("node_id",)`, drop `"scope"` from `NODE_DEFAULTS`, and describe `request_review` as "asks the platform for an independent referee of a plan or argument (approach, conjecture or lemma); a compiled node needs none"; delete `local_compile` and the `local_compile` result key; `_recruit_objective` prints the public status. In `NORMS`, the norm whose text is "Ask for a referee before investing heavily in formalization." (matched by its existing text, never by index) becomes `"Ask a referee to check a plan before a long formalization; compiled Lean needs no referee."`; delete playbook step "Get a referee." (renumber).
- [ ] **Step 7: Tests.** `set_status` in `tests/commons_helpers.py` keeps working for `accepted`, `refuted`, `abandoned`; delete the ladder and fidelity tests (`tests/test_commons_review.py` `:461`, `:673`, `:737`, `:773`, `:797`, `:807`, `:901`, `:928`, `:975`, `:993`, `:1051`, `:1137`, `:1188`, `:1226`, `:1247`, `:1545`, `:1586`, `:1609`, `:1631`, `:1701`; `tests/test_commons.py::test_illegal_transition_rejected`; the local-compile tests in `tests/test_society_tools.py` (`:1016`, `:1802`, `:1847`, `:2208`, `:2241`, `:2567`)). Retarget to `published` where a test's point survives: `test_lean_check_refuses_forged_local_compiles` becomes a check that a forged source is not published `verified`; `tests/test_statement_check.py::test_elaboration_tricks_cannot_forge_a_local_compile` asserts the forgery is not published `verified` (drop `_formal_node`'s `set_status` line). `test_runner_selects_and_executes_referee_requested_by_own_agent` asserts the review is recorded and the node stays `open`. `test_goal_accepted_hook_on_verified_target_receipt`: goals are now created `open`, not `formally_stated`, so its setup and its pre-acceptance assertion of the goal's status both read `"open"`. Replace `request_review(x, "informal", …)` with `request_review(x, …)` everywhere, and remove `"scope"` from tool calls.
- [ ] **Step 8: Docs.** RESEARCH_NETWORK: "Status" bullet — nodes are `open` until the author abandons them or the platform accepts or refutes them; a node inside an independently verified proof becomes `accepted`; S1's ladder values read as open. Referees bullet: plan reviews only, `REVIEW_UNNEEDED` for compiled nodes, verdicts recorded and negative ones posted as objections, panel bound unchanged, no fidelity reviews or vetoes. PLAN.md §2.2 and §5.2 say the same (the verifier is the only arbiter; referees check plans); §3.1 norm 7 and §3.7 playbook as in Step 6. IMPLEMENTATION_STATUS and FORMAL_ENVIRONMENT: "`compiles_locally`" → "a `verified` source rank".
- [ ] **Step 9: Run the tests**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_commons_review.py tests/test_commons.py tests/test_commons_discourse.py tests/test_society_tools.py tests/test_statement_check.py tests/test_society_scaffolding.py tests/test_society_simulation.py tests/test_society_metrics.py tests/test_commons_postgresql.py tests/test_commons_sources.py -q`
Expected: PASS; `nodes_by_status` in metrics still reports raw stored values.

- [ ] **Step 10: Commit**

```bash
git add src/physharness tests docs PLAN.md
git -c user.name=Kieran -c user.email=88352982+zubadestroyer1@users.noreply.github.com commit -m "feat: replace the node ladder and fidelity reviews with open nodes, plan reviews and proof-driven acceptance" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 13: Prune the catalog; `find_declaration` replaces library search and reads (#19)

**Files:**
- Create: `src/physharness/formal_tools/declaration_index.py` (guest script, standard library only, under 32 KiB)
- Modify: `src/physharness/orchestration/workspace_tools.py:254-370` (`find_declaration`, `_library_path`; `search_library` and `lookup_library_source` stay for the legacy catalog)
- Modify: `src/physharness/orchestration/society_tools.py` (tuples `:67-116`; delete `lean_sketch` with `hole_node`/`elaborate_holes` `:733-882`, `search_library`/`read_source` `:883-895` → `find_declaration`, `inbox` `:1197-1217`, `load_skill` `:1450-1458`; imports `:48`, `:60`)
- Modify: `src/physharness/orchestration/society_prompt.py` (delete `REFEREE_EXCLUDED_SKILLS`, `_skill_line`, both skills blocks, the `list_skills` import); `src/physharness/domain.py` (`ScaffoldingPolicy.skills` → `REMOVED_SCAFFOLDING_FIELDS["skills"]`); delete `src/physharness/skills/`
- Modify: `src/physharness/execution/stagnation.py:40-52` (`READ_TOOLS` adds `find_declaration`, `commons_fetch`); `tools/society_metrics.py:93-176` (`find_declaration` in `MATH_LEAN_COMPUTATION` and `LEAN_FORMALIZATION`; `RETIRED_SOCIETY_TOOLS`)
- Modify: `work/society-s1/run-plan.example.json` (`skills`), `PLAN.md` §3.3 table and §3.7 skills bullet, `docs/RESEARCH_NETWORK.md` tool table
- Test: create `tests/test_declaration_index.py`; `tests/test_society_tools.py`, `tests/test_society_scaffolding.py`, `tests/test_society_metrics.py:376-392`, `tests/test_statement_check.py`

**Interfaces:**
- Consumes: `WorkspaceTools.lookup_library_declaration` (`workspace_tools.py:230-252`) as the `#check` verifier.
- Produces: `WorkspaceTools.find_declaration(arguments, operation_id) -> dict` with `rows: list[str]` (`"Name signature — path:line"`, at most 20), `exact: bool`, `top: {"name", "module"} | None`, `did_you_mean: list[str]`, `indexed: int`, `environment_digest`, optional `verified: {"name", "ok", "output"}`; read mode returns `{"path", "start_line", "end_line", "text", "truncated"}`. `workspace_tools._DECLARATION_QUERIES` (host cache, 512 entries, keyed `(environment_digest, mode, query)`). `society_metrics.RETIRED_SOCIETY_TOOLS = frozenset({"inbox", "lean_sketch", "load_skill", "search_library", "read_source"})`. Task 20 wraps the tool to add `library_notes`.

- [ ] **Step 1: Write the failing tests** (`tests/test_declaration_index.py`)

```python
import json
import subprocess
import sys
from importlib import resources

SCRIPT = resources.files("physharness.formal_tools") / "declaration_index.py"
DOT = (
    "namespace Matrix\n\ntheorem dotProduct_comm (v w : Fin 2 → ℕ) :\n"
    "    dotProduct v w = dotProduct w v := by\n  simp\n\nend Matrix\n\n"
    "def dotProduct (v w : Fin 2 → ℕ) : ℕ := 0\n"
)

def run(*args):
    done = subprocess.run([sys.executable, str(SCRIPT), *args], capture_output=True,
                          text=True, timeout=60, check=True)
    return json.loads(done.stdout)

def test_index_ranks_names_suggests_and_reads_bounded(tmp_path):
    root = tmp_path / "mathlib"
    (root / "Mathlib" / "Data").mkdir(parents=True)
    (root / "Mathlib" / "Data" / "Dot.lean").write_text(DOT)
    index = tmp_path / "work" / ".cache" / "decls.tsv"
    query = ("query", "--index", str(index), "--root", str(root), "--mode", "name", "--")
    found = run(*query, "dotProduct")
    assert found["rows"][0] == "dotProduct (v w : Fin 2 → ℕ) : ℕ — mathlib/Mathlib/Data/Dot.lean:9"
    assert found["exact"] is True and found["top"] == {"name": "dotProduct", "module": "Mathlib.Data.Dot"}
    assert index.exists() and found["indexed"] == 2
    renamed = run(*query, "Matrix.dotProduct")
    assert renamed["exact"] is False and "dotProduct" in renamed["did_you_mean"]
    assert run(*query, "dotProduct_comm")["rows"][0].startswith("Matrix.dotProduct_comm (v w")
    read = run("read", "--root", str(root), "mathlib/Mathlib/Data/Dot.lean", "3")
    assert read["start_line"] == 1 and "dotProduct_comm" in read["text"]
    assert len(read["text"].encode()) <= 4000
```

  `tests/test_society_tools.py`: `test_catalog_has_find_declaration_and_no_retired_tools` — `widest()` and `referee_catalog()` contain `find_declaration` and none of `RETIRED_SOCIETY_TOOLS`; a dispatched `find_declaration` call reaches a `FakeWorkspace.find_declaration` (add it: record the call, return `{"rows": [], "exact": False}`). Update `REFEREE_TOOLS` (drop `search_library`, `read_source`, `inbox`, `load_skill`; add `find_declaration` after `lean_check`). `tests/test_society_scaffolding.py`: `test_scaffolding_policy_names_removed_fields` gains `"skills"`.
- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_declaration_index.py tests/test_society_tools.py tests/test_society_scaffolding.py -q -k "index or find_declaration or removed_fields"`
Expected: FAIL (no script, no tool).

- [ ] **Step 3: The guest script.** CLI `query --index P --root D [--root D] --mode name|type -- QUERY` and `read --root D [--root D] PATH LINE`; prints one JSON object.
  - Build the index when `P` is missing (create parents; write `P.tmp`, then `os.replace`): walk each root sorted, skipping `.lake` and `.git`, at most 20,000 `.lean` files and 400,000 rows. `MAX_INDEX_BYTES = 64 * 1024 * 1024` (64 MiB, on `/work/.cache`, a RAM-backed tmpfs): if the rows written so far would exceed it, stop indexing without writing `P.tmp` to `P`, print `{"error": "index_too_large", "bytes": <written so far>}` and exit 3 (the host's existing nonzero-exit handling then reports `declaration_index_failed`; give it the remediation "Past the header-index cap; use `shell` with `rg <query> /opt/sources/mathlib /opt/sources/physlib` instead."). A declaration starts at column 0: `^(?:@\[[^\]]*\]\s*)?(?:(?:private|protected|noncomputable|nonrec|partial|unsafe)\s+)*(theorem|lemma|def|abbrev|instance|structure|class|inductive|axiom|opaque)\s+([^\s:({\[⦃]+)(.*)$`. Track `namespace X` (push each dotted part) and `end X` (pop them); the name is qualified by the stack unless it starts with `_root_.`. The signature is the rest of the line plus up to 6 continuation lines, cut at the first `:=`, ` where` or a line starting with `|`, whitespace-collapsed, at most 300 characters. A row is `name \t signature \t <root basename>/<relative path> \t line \t module` (module = relative path without `.lean`, `/` → `.`).
  - Rank (`mode="name"`): exact name 100; `name.endswith("." + q)` 90; case-insensitive equal 85; case-insensitive suffix 80; case-insensitive substring `60 - min(20, len(name) - len(q))`; else 40 × the share of the query's `.`/`_` parts found in the name when that share ≥ 0.5; else 0. `mode="type"`: 50 × the share of the query's `[\w.']+` tokens found in the signature. Sort by `(-score, len(name), name)`, keep score > 0, top 20, each rendered `f"{name} {signature} — {path}:{line}"` (at most 400 characters). `exact` = best score ≥ 85; `top` = the best row's name and module; when not exact, `did_you_mean` = `difflib.get_close_matches(last dotted part of the query, the last parts of all names, n=5, cutoff=0.75)` mapped to the first full name ending in each; `indexed` = the row count.
  - `read`: PATH must be `<root basename>/…` under a given root, end in `.lean` and contain no `..` (else print `{"error": "unsafe_path"}` and exit 2); return lines `max(1, LINE-40)` … `LINE+40`, cut to 4,000 UTF-8 bytes on a character boundary, with `truncated`.
- [ ] **Step 4: Host side** (`workspace_tools.py`). Factor the path rule of `lookup_library_source` into `_library_path(path)` (same `UNSAFE_PATH` error). `find_declaration(arguments, operation_id)`: exactly `query`, or `path` with `line` (else `INVALID_QUERY`, 422); upload the script once per `WorkspaceTools` to `.physharness/declaration_index.py` (like `LeanSession._upload_checker`); query mode checks `_DECLARATION_QUERIES` first (evict the oldest past 512), else runs `[*GUEST_PYTHON, ".physharness/declaration_index.py", "query", "--index", f".cache/physharness/decls-{digest[:16]}.tsv", "--root", "/opt/sources/physlib", "--root", "/opt/sources/mathlib", "--mode", mode, "--", query]` with `cwd="."`, `timeout_seconds=min(self.policy.timeout_seconds, 120)`, `max_output_bytes=65536` (`.cache` is never archived, so the index stays out of checkpoints); a nonzero exit returns `{"rows": [], "reason_code": "declaration_index_failed", "diagnostics": result}` uncached. With `verify` and an exact hit, call `self.lookup_library_declaration({"name": top["name"], "imports": [top["module"]]}, operation_id + ":verify")` and add `verified = {"name", "ok": reason_code is None, "output": stdout[:2000]}`. Every result carries `environment_digest` and `"mechanism": "declaration_header_index"`.

  **Real-image timing (F13).** A full Mathlib + Physlib header scan (~8k files, up to 400,000 rows) is otherwise unmeasured for wall time and for `/work` tmpfs use. Before Step 5, using the same `physharness-pilot` container session and protocol as Task 2 Step 5 (G7's other permitted Docker/Colima use): provision a real container, upload the script, and time one cold `query --index .cache/physharness/decls-test.tsv --root /opt/sources/physlib --root /opt/sources/mathlib --mode name -- Nat.add` run through it. Record the wall time, the index's row count and its byte size in the task report. If that run exceeds 60 seconds or `MAX_INDEX_BYTES`, drop the eager, cached full-index build above in favor of a lazily built, per-query search with no persistent index file: shell out to `rg --no-heading --line-number --max-count 200 <query> /opt/sources/mathlib /opt/sources/physlib`, rank and render the matching lines the same way (§ above), capped at 20 rows; keep the same result shape (`rows`, `exact`, `top`, `did_you_mean`, `indexed`, `environment_digest`) so `workspace_tools.find_declaration` and the tool schema are unaffected either way.
- [ ] **Step 5: Society catalog.** Delete the tools and helpers listed under Files. Register `find_declaration` where `search_library` was:

```python
        add(
            "find_declaration",
            {
                "query": text(200, "A declaration name or fragment (mode name), or words of its type (mode type).", nullable=True),
                "mode": choice(("name", "type"), "name: match names; type: match signatures."),
                "path": text(PATH, "Read mode: a path from a result row (mathlib/… or physlib/…).", nullable=True),
                "line": integer(1, 10_000_000, "Read mode: the line to read around.", nullable=True),
                "verify": {"type": "boolean", "description": "Also #check the top row's exact signature in Lean (slower)."},
            },
            lambda a, k: workspace_tools.find_declaration(a, k),
            "Find pinned Mathlib and Physlib declarations: ranked rows 'Name signature — path:line' "
            "(at most 20) with did-you-mean names when nothing matches exactly. With path and "
            "line, read ±40 lines (at most 4,000 bytes) around a declaration; never a whole file.",
            defaults={"query": None, "mode": "name", "path": None, "line": None, "verify": False},
        )
```

  `SOCIETY_TOOL_NAMES`: drop `lean_sketch`, `search_library`, `read_source`, `inbox`, `load_skill`; put `find_declaration` after `lean_check`. `REFEREE_TOOL_NAMES`: the same edits. Remove `ScaffoldingPolicy.skills` (add `"skills": "technique notes were never loaded in S1"` to `REMOVED_SCAFFOLDING_FIELDS`), the skills blocks in `society_prompt.py`, the `skills` key in `run-plan.example.json`, and `src/physharness/skills/`.
- [ ] **Step 6: Metrics and stagnation.** Keep the retired names in their buckets (S1 exports use them) and change `test_every_catalog_tool_has_a_documented_bucket`'s last check to `set().union(*buckets.values()) == catalog | metrics_tool.RETIRED_SOCIETY_TOOLS`. Add `find_declaration` to `MATH_LEAN_COMPUTATION` and `LEAN_FORMALIZATION`; add `find_declaration` and `commons_fetch` to `stagnation.READ_TOOLS`.
- [ ] **Step 7: Old tests.** Delete the `lean_sketch` tests (`tests/test_society_tools.py:1067`, `:1787`, `:2589`), `test_inbox_acks_then_reads` (`:1146`), the skill tests (`tests/test_society_scaffolding.py:81-127` and the skills assertions of `test_constitution_respects_policy_flags_and_length`), and every remaining import of `physharness.skills`; drop the `lean_sketch` description assertion in `test_society_schemas_bound_arrays_without_string_length_keywords`. `test_society_catalog_without_literature_or_review`: drop its `ScaffoldingPolicy(skills=False)` construction (the field is gone) and drop `inbox` from the bare catalog's expected tool list (Task 20 later adds `library_notes` to this same list). `LeanSession.sketch_goals` and its tests stay (it is not a tool).
- [ ] **Step 8: Docs.** PLAN.md §3.3 table: Lean `lean_check`; Library `find_declaration`; drop `inbox`, `lean_sketch`, `load_skill`; §3.7: "Technique skills were removed after S1 (never loaded)." RESEARCH_NETWORK tool table likewise.
- [ ] **Step 9: Run the tests**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_declaration_index.py tests/test_society_tools.py tests/test_society_scaffolding.py tests/test_society_metrics.py tests/test_statement_check.py tests/test_society_simulation.py tests/test_run_control.py tests/test_execution_claude.py -q`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add -A src/physharness tools work/society-s1 PLAN.md docs/RESEARCH_NETWORK.md tests
git -c user.name=Kieran -c user.email=88352982+zubadestroyer1@users.noreply.github.com commit -m "feat: replace library search and reads with find_declaration and retire unused society tools" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 14: Stub skeletons with `lean_check(stubs=true)` (#21)

**Files:**
- Modify: `src/physharness/orchestration/lean_session.py:529-547` (add `declaration_spans` after `top_level_declarations`)
- Modify: `src/physharness/orchestration/society_tools.py` (`stub_declarations`; builder `lean_check` gains `stubs`), `society_prompt.py` (`_playbook` steps 5–6)
- Modify: `src/physharness/commons.py:477-521` (`read_node.rests_on` gains `stubs`)
- Modify: `docs/RESEARCH_NETWORK.md` (Lemma store: skeletons), `PLAN.md` §3.7 sketch-then-fill bullet, §5.3
- Test: `tests/test_society_tools.py`

**Interfaces:**
- Consumes: `split_imports`, `expand_commons`, `node_module` (Tasks 9–10); `LeanSession.elaborate_statements(header, entries, *, operation_id)`; `service.create_node`, `service.set_lean_statement`, `service.link_nodes`; `_elaboration`, `_infrastructure_failure` (`society_tools.py`).
- Produces: `lean_session.declaration_spans(source: str) -> list[tuple[str, str, int, int]] | None` (`keyword, name, first_line, last_line`, 1-based inclusive; `None` when comments or literals change the line count); `society_tools.stub_declarations(source) -> list[tuple[str, str, int, int]] | None` (`name, signature, first, last` of top-level `theorem|lemma X <sig> := sorry` or `:= by sorry`); `lean_check` result `stubs: [{"lean_name", "node_id", "module", "created"}]` and `skeleton_source: str` (the published text).

- [ ] **Step 1: Write the failing tests** (`tests/test_society_tools.py`; import `declaration_spans`)

```python
SKELETON = (
    "import Mathlib\n\n"
    "theorem step_one : (1 : Nat) + 1 = 2 := by sorry\n\n"
    "theorem step_two : (2 : Nat) + 2 = 4 := sorry\n\n"
    "theorem trace_add : (1 : Nat) + 1 = 2 := step_one\n"
)

def test_declaration_spans_follow_source_lines():
    spans = declaration_spans("-- a /- comment\nnamespace N\ntheorem hidden : True := trivial\nend N\n" + SKELETON)
    assert [(name, first, last) for _, name, first, last in spans] == [
        ("step_one", 7, 8), ("step_two", 9, 10), ("trace_add", 11, 12)
    ]

async def test_skeleton_publication_creates_linked_stub_nodes(lab):
    service, author, exp, _, (alpha, _) = society_lab(lab)
    agent, context = running(service, author, exp, alpha.branch_id)
    workspace = FakeWorkspace()
    tools = profile(service, agent, context, workspace=workspace)
    parent = await call(tools, "commons_node", lemma_args())
    await call(tools, "commons_node", {"action": "set_lean_statement", "node_id": parent["id"], **LEAN})
    checked = await call(tools, "lean_check", {"source": SKELETON, "node_id": parent["id"], "stubs": True})
    assert [(s["lean_name"], s["created"]) for s in checked["stubs"]] == [("step_one", True), ("step_two", True)]
    for stub in checked["stubs"]:
        node = service.read_node(stub["node_id"], agent)["node"]
        assert node["lean_elaborated"] is True and stub["module"] == node["lean_module"]
    edges = {e["node_id"] for e in service.read_node(parent["id"], agent)["edges_out"] if e["relation"] == "depends_on"}
    assert edges == {s["node_id"] for s in checked["stubs"]}
    skeleton = checked["skeleton_source"]
    assert "theorem step_one" not in skeleton and skeleton.count("import Commons.N") == 2
    assert "theorem step_one : (1 : Nat) + 1 = 2 := sorry" in workspace.lean.sources[-1]
    again = await call(tools, "lean_check", {"source": SKELETON, "node_id": parent["id"], "stubs": True})
    assert [s["created"] for s in again["stubs"]] == [False, False]
```

  Also (specified): `test_a_stub_that_needs_a_skeleton_definition_is_not_created` (`FakeLean(elaborates=lambda h, n, s: n != "step_two")`: `step_two` reported `{"created": False, "reason": "stub_needs_definition_node"}` and stays in the skeleton text); `test_filling_a_stub_with_another_signature_is_not_published` (`lean_check` on the stub node with a source declaring `theorem step_one : (1 : Nat) + 1 = 3 := …` → `published["reason"] == "statement_not_found"`).
- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_society_tools.py -q -k "spans or skeleton or stub"`
Expected: FAIL.

- [ ] **Step 3: Spans** (`lean_session.py`):

```python
def declaration_spans(source: str) -> list[tuple[str, str, int, int]] | None:
    """(keyword, name, first_line, last_line) of each top-level declaration, 1-based and
    inclusive; None when comments or literals change the line structure."""
    code = lean_code(source)
    if code.count("\n") != source.count("\n"):
        return None
    starts, blocks = [], 0
    for match in _COMMAND.finditer(code):
        keyword, line = match.group(1), code.count("\n", 0, match.start()) + 1
        if keyword in _BLOCKS:
            blocks += 1
        elif keyword == "end":
            blocks = max(0, blocks - 1)
        named = keyword not in (*_BLOCKS, "end", "variable") and not blocks
        name = _NAME.match(code, match.end()) if named else None
        starts.append((keyword if name else None, name.group(1) if name else None, line))
    total, spans = source.count("\n") + 1, []
    for index, (keyword, name, line) in enumerate(starts):
        if keyword is not None:
            end = starts[index + 1][2] - 1 if index + 1 < len(starts) else total
            spans.append((keyword, name, line, max(line, end)))
    return spans
```

  (The span of the last declaration runs to the end of the file, trailing blank lines included; the test expects that.)
- [ ] **Step 4: Stubs in `lean_check`.** Add `"stubs": {"type": "boolean", "description": "With node_id: turn each top-level 'theorem X … := sorry' into a stub node the skeleton imports."}` (default `False`) to the builder's schema. `stub_declarations(source)` keeps the spans whose keyword is `theorem`/`lemma` and whose `lean_code` text after the name matches `(?s)\s*(?P<signature>.*?):=\s*(?:by\s+)?sorry\s*`, with a whitespace-collapsed signature passing `signature_problem`. With `stubs` and `node_id` (P):
  1. `None` from `stub_declarations` → `invalid("stubs: comments or literals change the skeleton's line structure; simplify them.")`; no stubs → an ordinary check.
  2. The stub header is the file's environment import lines plus its `open`/`set_option`/`universe` lines before the first declaration; it must pass `header_problem` (else `invalid("stubs need a plain header: imports, open, set_option, universe.")`).
  3. Reuse P's `depends_on` targets whose `_lean_digest(lean_header, lean_name, lean_statement)` equals the stub's; elaborate the rest in one `lean().elaborate_statements(header, [(name, sig, ()) ...], operation_id=f"{k}:stubs")`. A failed one is reported `created: False` with reason `stub_needs_definition_node` (Lean judged it) or `lean_infrastructure_failure` (`_infrastructure_failure`), and stays in the text.
  4. For each elaborated stub: `create_node(NodeCreate(node_type="lemma", title=name, statement=f"Stub in {P['title'][:150]}: {name}", lean_header=header, lean_name=name, lean_statement=sig))`, then `set_lean_statement(id, header, name, sig, _elaboration(result))`, then `link_nodes(experiment_id, P, "depends_on", id)`, with keys `f"{k}:stub:{name}"`, `…:stub-lean:…`, `…:stub-link:…`.
  5. Rewrite the source: delete each stubbed span's lines and insert `import <module>` lines right after the file's leading import lines. Check and publish the rewritten text as P's module through the normal path; return `stubs` and `skeleton_source`.
  `read_node.rests_on` adds `stubs`: the ids of dependencies whose source state is `stub`.
- [ ] **Step 5: Prompt and docs.** `_playbook` steps "Sketch the Lean proof with holes." / "Fill the holes." become "Optionally publish a Lean skeleton whose sorry lemmas become stub nodes (lean_check with stubs=true)." / "Fill stubs by publishing their sources; submit the skeleton once none remain." (update the copy in `tests/test_society_scaffolding.py`). RESEARCH_NETWORK: "A skeleton is any node whose published source imports stub nodes; `lean_check(stubs=true)` creates them. It is optional." PLAN.md §3.7 sketch-then-fill and §5.3: the same, replacing `lean_sketch` holes.
- [ ] **Step 6: Run the tests**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_society_tools.py tests/test_lean_session.py tests/test_society_scaffolding.py tests/test_commons_sources.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/physharness/orchestration/lean_session.py src/physharness/orchestration/society_tools.py src/physharness/orchestration/society_prompt.py src/physharness/commons.py docs/RESEARCH_NETWORK.md PLAN.md tests/test_society_tools.py tests/test_society_scaffolding.py
git -c user.name=Kieran -c user.email=88352982+zubadestroyer1@users.noreply.github.com commit -m "feat: turn sorry lemmas of a skeleton into importable stub nodes" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 15: Scoped recruits that end when their work is delivered (#23)

**Files:**
- Modify: `src/physharness/orchestration/society_tools.py:119-127` (`HATS["librarian"]`), `:467-489` (`_recruit_objective`), `:1219-1297` (`recruit`: `until_proved`, description); `society_prompt.py` (the "Recruit when…" norm, matched by text)
- Modify: `src/physharness/workforce_models.py:47-68` (`scope_node_id`), `src/physharness/workforce.py:662-713` (validate, fingerprint, `task_extra`)
- Modify: `src/physharness/execution/responses.py:1085-1117` (`COMPLETION_REASONS`)
- Modify: `src/physharness/orchestration/research_worker.py:1469-1532` (boundary hook), `:1940-1956` (completion note), new `ResearchTaskExecutor._society_completion`
- Modify: `docs/RESEARCH_NETWORK.md` (Recruits bullet), `PLAN.md` §3.4
- Test: `tests/test_society_tools.py`, `tests/test_network_runtime.py`, `tests/test_society_messages.py` (legacy fingerprint still holds)

**Interfaces:**
- Consumes: `lean_source`, `COMPLETE_RANKS` (Task 9); `service.return_result(task_id, *, evidence_status, artifact_ids, unresolved_obligations, summary, execution_failure, actor, key)`.
- Produces: `RecruitResearcherRequest.scope_node_id: str | None = None` (excluded from the fingerprint when `None`); task payload `scope = {"node_id", "lean_statement_sha256", "module"}`; error `SCOPE_NEEDS_STATEMENT` (422); `responses.COMPLETION_REASONS = frozenset({"target_verified", "result_returned", "scope_proved", "scope_closed"})`; `ResearchTaskExecutor._society_completion(task, agent, holder, fence) -> str | None`.

- [ ] **Step 1: Write the failing tests** (`tests/test_society_tools.py`; import `_recruit_objective`):

```python
SCOPE = "Scope: this brief only. The target statement is context, not your assignment:"

def test_every_recruit_brief_gets_a_scope_paragraph():
    joined = _recruit_objective("Find the coin theorem.", None, "librarian", detached=False)
    assert SCOPE in joined and "call return_result with what you have; your session then ends." in joined
    assert "look up library names, signatures and duplicates for this brief, then return" in joined
    detached = _recruit_objective("Explore.", None, None, detached=True)
    assert "post what you have on your focus node and finish" in detached

async def test_until_proved_needs_an_elaborated_focus_statement(lab):
    service, author, exp, _, (alpha, _) = society_lab(lab)
    agent, context = running(service, author, exp, alpha.branch_id)
    tools = profile(service, agent, context)
    bare = await call(tools, "commons_node", lemma_args())
    refused = await call(tools, "recruit", {"brief": "Prove it.", "title": "Prover",
                                            "focus_node_id": bare["id"], "until_proved": True})
    assert refused["error"]["code"] == "SCOPE_NEEDS_STATEMENT"
```

  Also (specified): `test_joined_recruit_ends_after_return_result` — `society_runner` with a route that answers the root (objective "Root") with a `recruit` call, then a final message, and the recruit (objective starting "Look up") with `return_result` at phase 0; the recruit makes exactly one provider request, its task is `completed`, and the root's joined handoff proceeds; `test_scoped_recruit_completes_once_its_node_has_a_complete_source` — a recruit with `until_proved` whose phase 0 is `lean_check(node_id=<scope>)` of `PROOF`: no second recruit request, task `completed`, and a recorded `return_result` naming the published artifact; `test_boundary_hook_completion_reasons` in `tests/test_network_runtime.py` next to `:59` — `ResponsesRuntime._maybe_handoff` accepts each `COMPLETION_REASONS` member and rejects `{"complete_reason": "other"}` with `INVALID_CONTINUATION`.
- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_society_tools.py tests/test_network_runtime.py -q -k "scope or until_proved or return_result or completion_reasons"`
Expected: FAIL.

- [ ] **Step 3: Objective and tool.** `HATS["librarian"] = "look up library names, signatures and duplicates for this brief, then return"`. `_recruit_objective(brief, focus, hat, *, detached, scope=None)` appends, after the hat line:

```python
SCOPE_JOINED = (
    "Scope: this brief only. The target statement is context, not your assignment: do not "
    "attempt, assemble or submit the whole target. When the brief is done or blocked, call "
    "return_result with what you have; your session then ends."
)
SCOPE_DETACHED = (
    "Scope: this brief only. The target statement is context, not your assignment: do not "
    "attempt, assemble or submit the whole target. When the brief is done or blocked, post "
    "what you have on your focus node and finish."
)
```

  and with `scope`: `f"Prove exactly theorem {name} {statement} (node {id8}). Publish it with lean_check(node_id={id8}). Your task ends by itself once a complete source for the node is recorded, by you or anyone; do not work beyond it."`. `recruit` gains `"until_proved": {"type": "boolean", "description": "End the recruit once the focus node has a complete published source."}` (default `False`); with it, the tool itself raises `SCOPE_NEEDS_STATEMENT` (below) when there is no focus node or it lacks an elaborated Lean statement, then passes `scope_node_id=focus["id"]`; its description adds "Give one narrow deliverable (a named lemma with its Lean signature, or a specific lookup); narrow recruits cost least." The `recruit` handler calls `_recruit_objective(a["brief"], focus, a["hat"], detached=a["detached"], scope=focus if a["until_proved"] else None)`. In `NORMS`, the norm whose text is "Recruit when a piece can proceed independently." (matched by its existing text, never by index) becomes `"Recruit for one narrow deliverable (a named lemma with its signature, or a lookup); recruits end when they return."`
- [ ] **Step 4: Scope in the request.** `recruit_researcher`: fingerprint `request.model_dump(mode="json", exclude={"scope_node_id"} if request.scope_node_id is None else None)`; with a scope, read the node (`self._commons_node(session, id, actor, experiment_id)`) and require it open, `lean_elaborated`, with `lean_name` and `lean_statement`, else `HarnessError("SCOPE_NEEDS_STATEMENT", "until_proved needs a focus node with an elaborated Lean statement.", status=422, remediation="Record the statement with set_lean_statement first.")`; pass `task_extra={"scope": {"node_id", "lean_statement_sha256", "module": node_module(node)}}` to `_new_branch_task`.
- [ ] **Step 5: Completion.** `responses.py`: add `COMPLETION_REASONS`; `_maybe_handoff` accepts `isinstance(request, dict) and set(request) == {"complete_reason"} and request["complete_reason"] in COMPLETION_REASONS` and sets `completion_reason=request["complete_reason"]` (the `target_verified` behaviour is unchanged). `research_worker.py`: in `boundary_hook`, after the `target_verified` check and only for `society and not referee`: `reason = self._society_completion(self.service.get_record("task", task_id, actor), agent, holder, lease["fence"])` and `if reason: return {"complete_reason": reason}`. `_society_completion`: with `task["scope"]`, read the node; when `lean_source.rank in COMPLETE_RANKS` and its `lean_statement_sha256` equals the scope's, record (if joined and no `return_result` yet) `return_result(evidence_status="unverified", artifact_ids=[artifact_id], unresolved_obligations=[], summary=f"Node {id8} is proved as {module}; import it.", execution_failure=None)` under `worker_effects(agent, task_id, holder, fence)` with key `f"scope-result:{task_id}"`, and return `"scope_proved"`; a closed node returns `"scope_closed"`. Otherwise a joined task with a recorded `return_result` returns `"result_returned"`. The output artifact's empty-text fallback becomes a table: `result_returned` "The recruit returned its result to its parent; its session ended.", `scope_proved` "The recruit's node has a complete published source; its session ended.", `scope_closed` "The recruit's node was closed; its session ended." (`target_verified` unchanged).
- [ ] **Step 6: Docs.** RESEARCH_NETWORK Recruits bullet: the scope paragraph, `until_proved`, and "a joined recruit's session ends after `return_result`". PLAN.md §3.4 librarian: "library names, signatures and duplicates for one brief, then return".
- [ ] **Step 7: Run the tests**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_society_tools.py tests/test_network_runtime.py tests/test_joined_delegation.py tests/test_society_messages.py tests/test_society_scaffolding.py tests/test_society_simulation.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/physharness docs/RESEARCH_NETWORK.md PLAN.md tests
git -c user.name=Kieran -c user.email=88352982+zubadestroyer1@users.noreply.github.com commit -m "feat: scope recruit briefs and end recruits when their work is delivered" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 16: Event waits: the wait, its wake conditions, and the long pole (#14, service side)

**Files:**
- Modify: `src/physharness/continuation.py:982-1144` (`request_event_wait` after `request_peer_wait`; `peer_wait_status` dispatches `kind == "events"` to `_event_wait_status`)
- Modify: `src/physharness/discussion.py` (`_pending_update(session, experiment, actor, after) -> bool`, using `_delivery_clauses` and `_push_skip` from Task 8)
- Modify: `src/physharness/commons.py:607-709` (`_long_pole`; `query_nodes(frontier=True)` returns `long_pole` and, when empty, `long_pole_hint`)
- Modify: `src/physharness/orchestration/society_tools.py:1323-1349` (`wait`), `society_prompt.py` (`NORMS`)
- Modify: `docs/RESEARCH_NETWORK.md` (a Waiting bullet), `PLAN.md` §3.1 (the `wait` episode)
- Test: create `tests/test_event_waits.py`; `tests/test_commons.py`

**Interfaces:**
- Consumes: `_delivery_clauses`, `_push_skip` (Task 8); `_live_claim_rows`, `_experiment_nodes`, `_experiment_dependencies`, `_depends_closure`.
- Produces: `continuation.EVENT_WAIT_MIN_SLEEP_SECONDS = 20`, `EVENT_WAIT_DEFAULT_SECONDS = 1800`; `ContinuationMixin.request_event_wait(task_id, watch_ids: list[str], timeout_seconds: int, actor, key) -> {"task_id", "intent", "revision", "long_pole"}` storing intent reason `wait_for_events` with the ticket under `peer_wait` (so issue, pre-check, runner and availability plumbing carry it unchanged): `{"kind": "events", "experiment_id", "task_id", "branch_id", "watch_node_ids", "watch_branch_ids", "after_sequence", "event_after", "long_pole_ids", "requested_at", "deadline_at", "min_sleep_until"}`; `peer_wait_status` returns `{"ready", "reason", "message_id": None, "detail"}` with reasons `cancelled`, `target_verified`, `timeout`, `min_sleep`, `relevant_update`, `watched_event`, `long_pole_changed`, `waiting`; `CommonsMixin._long_pole(nodes, dependencies, claims, limit=3) -> (items, hint)` with items `{"id", "title", "open_minutes", "claimants": [{"branch_id", "route"}]}`.

- [ ] **Step 1: Write the failing tests** (`tests/test_event_waits.py`)

```python
"""S1 audit #14: waits that wake on relevant events, not only on one peer's message."""

from commons_helpers import set_status, society_lab
from test_society_tools import running

from physharness.commons_models import NodeCreate, NodePostCreate
from physharness.worker_authority import worker_effects

def park(service, author, exp, agent_branch, ids=(), timeout=600):
    agent, context = running(service, author, exp, agent_branch)
    with worker_effects(agent, context["task_id"], context["holder"], context["fence"]):
        waited = service.request_event_wait(context["task_id"], list(ids), timeout, agent, "wait")
    return agent, {**waited["intent"]["peer_wait"], "min_sleep_until": 0}

def lemma(service, exp, agent, title):
    return service.create_node(exp["id"], NodeCreate(node_type="lemma", title=title, statement=title + "."), agent, title)

def test_routed_peer_post_wakes_and_own_or_unrelated_posts_do_not(lab):
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    mine, theirs = lemma(service, exp, alpha, "Mine"), lemma(service, exp, beta, "Theirs")
    agent, ticket = park(service, author, exp, alpha.branch_id)
    service.post_on_node(mine["id"], NodePostCreate(kind="finding", abstract="Me."), alpha, "own")
    service.post_on_node(theirs["id"], NodePostCreate(kind="finding", abstract="Them."), beta, "other")
    assert service.peer_wait_status(ticket, agent)["reason"] == "waiting"
    service.post_on_node(mine["id"], NodePostCreate(kind="objection", abstract="Gap."), beta, "peer")
    assert service.peer_wait_status(ticket, agent)["reason"] == "relevant_update"

def test_watched_claims_and_the_long_pole_wake(lab):
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    goal = service.query_nodes(exp["id"], alpha, node_type="goal")["items"][0]
    first, second = lemma(service, exp, beta, "First"), lemma(service, exp, beta, "Second")
    for target in (first, second):
        service.link_nodes(exp["id"], goal["id"], "depends_on", target["id"], alpha, f"l-{target['id']}")
    agent, ticket = park(service, author, exp, alpha.branch_id, ids=[second["id"]])
    assert set(ticket["long_pole_ids"]) == {first["id"], second["id"]}
    set_status(service, first["id"], "abandoned")
    assert service.peer_wait_status(ticket, agent)["reason"] == "long_pole_changed"
    _, watched = park(service, author, exp, alpha.branch_id, ids=[second["id"]])
    service.claim_node(second["id"], "claim", beta, "beta-claims")
    assert service.peer_wait_status(watched, agent)["reason"] == "watched_event"

def test_min_sleep_debounces_and_the_deadline_wakes(lab):
    service, author, exp, _, (alpha, beta) = society_lab(lab)
    mine = lemma(service, exp, alpha, "Mine")
    agent, ticket = park(service, author, exp, alpha.branch_id)
    service.post_on_node(mine["id"], NodePostCreate(kind="finding", abstract="Hi."), beta, "p")
    assert service.peer_wait_status({**ticket, "min_sleep_until": 9e18}, agent)["reason"] == "min_sleep"
    assert service.peer_wait_status({**ticket, "deadline_at": 0}, agent)["reason"] == "timeout"
```

  Also (specified): `test_wait_tool_parks_on_events_and_shows_the_long_pole` (tool call `wait(for="events", ids=[<node id8>])` returns `long_pole` and records intent reason `wait_for_events`); `test_frontier_reports_the_long_pole_and_a_hint` (`tests/test_commons.py`: without goal edges `long_pole` is the most-waited-on open node, or empty with `long_pole_hint`); `test_legacy_peer_wait_tickets_still_wake` (a ticket without `kind` keeps today's reasons; the existing `tests/test_swarm_coordination_gaps.py` tests cover it — run them).
- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_event_waits.py -q`
Expected: FAIL (`request_event_wait` does not exist).

- [ ] **Step 3: Long pole** (`commons.py`, static, beside `_frontier`): open non-goal nodes on the goal's `depends_on` closure that depend on no other open node, oldest `created_at` first; when there are none, the open nodes with the most open dependents, requiring at least one open dependent (ties all kept); when no open node has any open dependent either, `([], "Link depends_on edges from the goal to its parts to show its long pole.")` — the static hint, never every open node (a maximum of zero ties them all). `open_minutes` from `created_at`; `claimants` from live claim rows (`{"branch_id", "route": payload.get("route")}`). `query_nodes(frontier=True)` returns `long_pole` (and `long_pole_hint` when set). The prompt (Task 7's `society_prompt_view`) and the compaction anchor read this same `query_nodes(frontier=True)["long_pole"]` computation, so they cannot diverge.
- [ ] **Step 4: The wait** (`continuation.py`). `request_event_wait` mirrors `request_peer_wait`'s binding, fence and `running` checks (`EVENT_WAIT_INVALID` for a bad timeout or more than 100 ids); each id must be a node or a branch of the experiment (else `EVENT_WAIT_SCOPE`); `after_sequence` is the reader's `ack_sequence` (0 without a reader), `event_after = self._discussion_max_sequence(session)`, `long_pole_ids` from `_long_pole` over `_experiment_nodes`/`_experiment_dependencies`, `min_sleep_until = now + min(EVENT_WAIT_MIN_SLEEP_SECONDS, timeout_seconds)`; event `task.event_wait_requested`. `peer_wait_status`: after the branch-authority check, `if peer_wait.get("kind") == "events": return self._event_wait_status(peer_wait, actor)`. `_event_wait_status` checks, in order: the experiment cancelled or the waiter task terminal → `cancelled`; `verified_target_receipt` → `target_verified`; deadline → `timeout`; `now < min_sleep_until` → not ready `min_sleep`; `self._pending_update(session, experiment, actor, after_sequence)` → `relevant_update`; an event after `event_after` of kind `commons.node_status`, `commons.node_claim`, `commons.edge_added` or `commons.source_published` whose `aggregate_id` is a watched node, or of kind `commons.node_created`, `commons.node_claim`, `commons.source_published` or `discussion.post_created` whose payload `branch_id` is a watched branch, excluding events whose payload `branch_id` is the waiter's own → `watched_event` (`detail = {"kind", "aggregate_id"}`); when a `commons.node_status`, `commons.edge_added` or `commons.source_published` event exists after `event_after` and the recomputed long-pole ids differ from `long_pole_ids` → `long_pole_changed`; else not ready `waiting`. `_pending_update` scans at most 100 events matching `_delivery_clauses(session, experiment, actor, reader_key, after)` and returns `True` at the first message or non-skipped post.
- [ ] **Step 5: Tool and norm.** `wait` becomes `for: tasks | events`, `ids` (optional; `ident("tasks: a recruit's task id; events: a node or branch to watch.", ("task", "commons_node", "branch"))`, no `min_items`), `timeout_seconds` (`events` only; default `EVENT_WAIT_DEFAULT_SECONDS`); `tasks` still requires ids. Description: "Sleep at no cost until something relevant happens, then resume with your context intact. for='events' wakes on a post or message routed to you, an event on a watched node or branch, a change in the goal's long pole, or the timeout; for='tasks' wakes when your recruits finish. Takes effect after this response." Add to `NORMS`: `"When you have nothing useful to do, wait for events (free while waiting) or finish; the goal's long pole is where help counts most."`
- [ ] **Step 6: Docs.** RESEARCH_NETWORK Waiting bullet (the conditions, the 20 s minimum sleep, the long pole in the wait result and the frontier). PLAN.md §3.1: "wait, which releases its worker slot until a relevant event (a routed post or message, a watched node or branch, a long-pole change) or a timeout".
- [ ] **Step 7: Run the tests**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_event_waits.py tests/test_commons.py tests/test_swarm_coordination_gaps.py tests/test_society_tools.py tests/test_society_scaffolding.py tests/test_research_discussion.py -q`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/physharness/continuation.py src/physharness/discussion.py src/physharness/commons.py src/physharness/orchestration/society_tools.py src/physharness/orchestration/society_prompt.py docs/RESEARCH_NETWORK.md PLAN.md tests/test_event_waits.py tests/test_commons.py tests/test_society_tools.py tests/test_society_scaffolding.py
git -c user.name=Kieran -c user.email=88352982+zubadestroyer1@users.noreply.github.com commit -m "feat: add event waits that wake on routed updates, watched work and the long pole" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 17: Event waits: native wake, event-head gating, and the idle stop (#14, runner side)

**Files:**
- Modify: `src/physharness/orchestration/research_worker.py:1116-1126` (keep the pre-check's status), `:1683-1690` (`native_compatible`), `:1848-1851` (wake note), `:2470-2548` (runner gating and idle stop)
- Modify: `src/physharness/discussion.py:672-673` (public `event_head(actor) -> int`)
- Modify: `docs/EXECUTION.md` (continuations section, `:28-44`), `docs/RESEARCH_NETWORK.md` (Waiting bullet)
- Test: `tests/test_event_waits.py`

**Interfaces:**
- Consumes: `request_event_wait`, `peer_wait_status` event tickets, `query_nodes(...)["long_pole"]` (Task 16).
- Produces: `research_worker.WAIT_REASONS = frozenset({"wait_for_tasks", "wait_for_peer", "wait_for_events"})`; a society wait resumes natively with the appended user item `canonical_json({"type": "wake", "reason", ["children"], ["long_pole"]})`; runner `stop_reason` `SOCIETY_IDLE`; `DiscussionMixin.event_head(actor) -> int`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_event_waits.py`; import `society_runner`, `run_manifest`, `mock_client`, `response`, `tool_call`, `message`, `TaskCreate`, `json`, `httpx`)

```python
async def test_a_society_wait_resumes_natively_with_a_wake_note(lab):
    service, author, exp, branches, _ = society_lab(lab)
    root = service.create_task(TaskCreate(branch_id=branches[0]["id"], objective="Root"), author, "root")
    payloads = []

    async def route(request):
        if request.url.path.endswith("/input_tokens"):
            return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 10})
        payload = json.loads(request.content)
        payloads.append(payload)
        items = ([tool_call("wait", {"for": "events", "ids": [], "timeout_seconds": 1}, "w-1")]
                 if len(payloads) == 1 else [message("done")])
        return httpx.Response(200, json=response(items, response_id=f"r-{len(payloads)}"))

    runner, client = society_runner(service, route)
    try:
        report = await runner.run(run_manifest(exp, author, root))
    finally:
        await client.close()
    assert report["stop_reason"] is None and len(payloads) == 2
    first, resumed = payloads
    assert resumed["input"][: len(first["input"])] == first["input"]  # the transcript is kept
    wake = json.loads(resumed["input"][-1]["content"])
    assert wake["type"] == "wake" and wake["reason"] == "timeout"
```

  Also (specified): `test_runner_skips_wait_checks_while_the_event_head_is_unchanged` (monkeypatch `service.peer_wait_status` with a counter; a root parked with `timeout_seconds=2` and no events is checked at most 3 times, not every 0.25 s loop); `test_an_all_parked_society_stops_idle` (monkeypatch `continuation.EVENT_WAIT_MIN_SLEEP_SECONDS` to `0` or `1` so a ticket's minimum sleep cannot race the manifest timeout; build a `TeamRunManifest` directly, with `task_ids` listing both roots — not `run_manifest`, whose `task_ids=[root_task["id"]]` cannot take a second root — and a `timeout_seconds` well above the patched minimum sleep; two roots each wait for events with `timeout_seconds=3600`; the report's `stop_reason == "SOCIETY_IDLE"` within the manifest timeout and both tasks stay non-terminal); `test_legacy_waits_still_resume_portably` (a legacy `wait_for_peer` continuation stays `portable`; `tests/test_swarm_coordination_gaps.py::test_waiting_peer_releases_capacity_and_resumes_on_reply` passes unchanged).
- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_event_waits.py -q -k "natively or head or idle"`
Expected: FAIL (the resumed request restarts from a fresh prompt).

- [ ] **Step 3: Native wake.** Keep the executor pre-check's `peer_status` in a local `wake_status` (`None` when no check ran). `native_compatible` accepts `ready["reason"] == "joined_children" or (society and ready["reason"] in WAIT_REASONS)`, with the existing model, limits, tool-digest and workspace checks. When `native_compatible and society and ready["reason"] in WAIT_REASONS`, pass `canonical_json(wake)` instead of `prompt` to `start_from_handoff`, where `wake = {"type": "wake", "reason": (wake_status or {}).get("reason") or ready["reason"]}`, plus `children = self.service.delegated_task_statuses(task_id, ready["wait_task_ids"], agent)` when it waited on tasks and `long_pole = query_nodes(..., frontier=True, limit=1).get("long_pole")` when non-empty. (`start_from_handoff` keeps the original anchor, so compaction is unaffected.) The routed posts arrive at the next boundary through Task 8's compact lines.
- [ ] **Step 4: Gating and idle stop** (`ResearchTeamRunner.run`). Once per loop read `head = self.service.event_head(actor)`. Keep `wait_checks: dict[task_id, (head, checked_at, reason)]`. For a ticket with `kind == "events"` call `peer_wait_status` only when there is no entry, the head moved, `now >= deadline_at`, or `checked_at < min_sleep_until <= now`; store the result's reason. In the `if not active and not checks:` block, before the `peer_wait` sleep: when the experiment has a society, at least one pending task holds an event ticket, every pending task is waiting (a `ready_continuation` with `peer_wait` or `wait_task_ids`), and every event ticket's stored reason is `waiting` at the current head, set `stop_reason = "SOCIETY_IDLE"` and break. Legacy tickets keep today's polling.
- [ ] **Step 5: Docs.** `docs/EXECUTION.md`: "In a society, a wait (`wait_for_events`, `wait_for_tasks`) resumes natively: the transcript is kept and a short wake note (reason, children, long pole) is appended. Other continuations are unchanged." RESEARCH_NETWORK Waiting bullet: wake checks run only when new events exist; a run whose agents all wait with nothing admissible stops with `SOCIETY_IDLE`.
- [ ] **Step 6: Run the tests**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_event_waits.py tests/test_swarm_coordination_gaps.py tests/test_joined_delegation.py tests/test_controller_continuation.py tests/test_society_tools.py tests/test_network_runtime.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/physharness/orchestration/research_worker.py src/physharness/discussion.py docs/EXECUTION.md docs/RESEARCH_NETWORK.md tests/test_event_waits.py
git -c user.name=Kieran -c user.email=88352982+zubadestroyer1@users.noreply.github.com commit -m "feat: resume society waits natively and stop an idle society" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 18: Admit society work by dollars; referees get their own slot pool (#16)

**Files:**
- Modify: `src/physharness/workforce_models.py:13-25` (`ConfigureWorkforceRequest`)
- Modify: `src/physharness/workforce.py:23-31` (constants, money helpers), `:285-312` (`_admit_research_tasks`), `:314-376` (`configure_workforce`), `:950` (`research_capacity`: `None` caps)
- Modify: `src/physharness/domain.py` (`SocietyPolicy.referee_slots`), `src/physharness/commons_review.py` (`request_review` admits with `referee=True`), `src/physharness/mcp_server.py:34-51` (optional caps, `admission_floor_usd`)
- Modify: `src/physharness/orchestration/research_worker.py:2470-2548` (runner pools; `max_tasks` counts research tasks)
- Modify: `docs/RESEARCH_NETWORK.md` (Workforce and Referees bullets), `work/society-s1/RUN_PLAN.md:80,93-98` (the S1 cap arithmetic is S1-only), `run-plan.example.json` (`referee_slots: 2`)
- Modify: `tests/commons_helpers.py` (`society_lab` gains a `concurrency=2` pass-through to `setup_experiment`'s `concurrency`, defaulting to today's value)
- Test: create `tests/test_society_admission.py`; `tests/test_commons_review.py::test_request_review_is_admitted_like_recruitment` (`:303`)

**Interfaces:**
- Produces: `ConfigureWorkforceRequest.max_total_tasks: int | None = None`, `max_pending_tasks: int | None = None`, `admission_floor_usd: Money | None = None` (no floor by default: `None` means `0`; the fingerprint and stored policy omit the floor when `None`); `_admit_research_tasks(session, experiment_id, actor, count=1, *, referee=False)`; error `ADMISSION_BUDGET` (`details` `remaining_usd`, `floor_usd`, `count`); `SocietyPolicy.referee_slots: int = 2` (0–32; stored policies without it read `.get("referee_slots", 0)`). Legacy experiments keep today's count caps and Task 3's messages (G1 covers prompts and the legacy freeze tests, not error text: Tier-0 error wording changed for every experiment back in Task 3, legacy included).

- [ ] **Step 1: Write the failing tests** (`tests/test_society_admission.py`)

```python
from decimal import Decimal

import pytest
from commons_helpers import society_lab

from physharness.commons_models import NodeCreate
from physharness.domain import Principal
from physharness.errors import HarnessError
from physharness.workforce_models import ConfigureWorkforceRequest, RecruitResearcherRequest

OPERATOR = Principal(id="operator", project_id="lab", role="operator")

def test_society_admission_is_by_dollars_and_caps_ignore_referees(lab):
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    service.configure_workforce(exp["id"], ConfigureWorkforceRequest(admission_floor_usd="1000000"), OPERATOR, "floor")
    helper = RecruitResearcherRequest(parent_branch_id=alpha.branch_id, title="Helper", objective="Help.", detached=True)
    with pytest.raises(HarnessError) as refused:
        service.recruit_researcher(exp["id"], helper, alpha, "recruit")
    error = refused.value
    assert error.code == "ADMISSION_BUDGET" and error.message.startswith("Budget, not input:")
    assert Decimal(error.details["floor_usd"]) == Decimal("1000000") and not error.retryable
    caps = ConfigureWorkforceRequest(max_total_tasks=1, max_pending_tasks=1, admission_floor_usd="0.01", expected_revision=1)
    service.configure_workforce(exp["id"], caps, OPERATOR, "caps")
    service.recruit_researcher(exp["id"], helper, alpha, "recruit-ok")
    node = service.create_node(exp["id"], NodeCreate(node_type="lemma", title="L", statement="L."), alpha, "l")
    assert service.request_review(node["id"], beta, "review")["review_task_id"]  # outside the caps
    with pytest.raises(HarnessError) as capped:
        service.recruit_researcher(exp["id"], helper.model_copy(update={"title": "Two"}), alpha, "recruit-2")
    assert capped.value.code == "TASK_TOTAL_CAP"
```

  Also (specified): `test_runner_reserves_referee_slots` (`society_lab(lab, concurrency=3, referee_slots=1)` — the database must allow three concurrent tasks before the runner's own pool split does; monkeypatch `continuation.EVENT_WAIT_MIN_SLEEP_SECONDS` to `0` or `1` and build a `TeamRunManifest` directly with `max_concurrency=3` and `task_ids` listing all three roots — not `run_manifest`, whose `task_ids=[root_task["id"]]` cannot take more than one root — with one requested referee: at most two research tasks run at once, and the referee starts while two roots run — record start order in the route); `test_referee_slots_zero_or_concurrency_one_keep_the_shared_pool` (the existing `run_manifest` with concurrency 1 behaves as before); `test_runner_task_limit_ignores_referee_attempts` (`max_tasks=1` still runs the root's referee); `test_configure_workforce_accepts_only_a_floor` (the API model validates without caps; the MCP tool body omits `admission_floor_usd` when unset).
- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_society_admission.py -q`
Expected: FAIL (caps are required; no floor).

- [ ] **Step 3: Admission** (`workforce.py`):

```python
def _micro(value):
    return int(Decimal(str(value)) * 1_000_000)

def _usd(units):
    return format(Decimal(units) / 1_000_000, "f")

    def _admit_by_budget(self, session, experiment_id, policy, count):
        """Society work is admitted while the remaining dollars cover the floor. There is no
        floor by default (admission_floor_usd is None, read as 0); an operator who sets one
        gets an early, budget-not-input refusal on top of the ledger's own hard stop (S1 #16)."""
        budget = session.get(BudgetRow, experiment_id)
        floor = _micro((policy.payload.get("admission_floor_usd") if policy else None) or "0")
        remaining = max(0, budget.max_cost - budget.spent - budget.reserved)
        if remaining < count * floor:
            raise HarnessError(
                "ADMISSION_BUDGET",
                f"Budget, not input: ${_usd(remaining)} remains and new work needs ${_usd(count * floor)}.",
                details={"remaining_usd": _usd(remaining), "floor_usd": _usd(floor), "count": count},
                remediation="Do not retry; continue with work already running, or finish.",
            )
```

  `_admit_research_tasks(..., *, referee=False)`: `experiment = self._workforce_lock(...)`; for a society experiment call `_admit_by_budget` first and return when `referee`; count caps then apply only when set (society: `policy.payload.get(key)`; legacy: the stored value or the 10,000 default, unchanged), and for a society both counts exclude referee tasks (`or_(record_json_text("hat").is_(None), record_json_text("hat") != REFEREE_HAT)`). `configure_workforce` stores `admission_floor_usd` (as a string) only when set and fingerprints `request.model_dump(mode="json", exclude={"admission_floor_usd"} if request.admission_floor_usd is None else None)`. `ConfigureWorkforceRequest.valid_caps` compares pending with total only when both are set. `research_capacity` passes stored `None` caps through. `request_review` calls `self._admit_research_tasks(session, experiment.id, actor, referee=True)`. `mcp_server.configure_workforce(experiment_id, operation_id, max_total_tasks=None, max_pending_tasks=None, expected_revision=None, synthesis_interval_posts=0, admission_floor_usd=None)` sends the floor only when given.
- [ ] **Step 4: Slot pools** (runner). Add `referee_slots: int = Field(default=2, ge=0, le=32)` to `SocietyPolicy`. In `run`: `slots = min((experiment.get("society") or {}).get("referee_slots", 0), manifest.max_concurrency - 1)`; track `active_referees: set[str]` (add on start, discard when a future completes) and `research_attempted: set[str]`. For each candidate, `is_referee = task.get("hat") == REFEREE_HAT`; with `slots`, skip (`continue`, not `break`) a referee when `len(active_referees) >= slots` and a research task when `len(active) - len(active_referees) >= manifest.max_concurrency - slots`; with `slots == 0` keep today's `break`. `max_tasks` and `TEAM_TASK_LIMIT` count `research_attempted` only. `reserve_resources` is unchanged, so the database still bounds the total at `max_concurrency`.
- [ ] **Step 5: Docs.** RESEARCH_NETWORK: society admission is by dollars (`admission_floor_usd`; no floor by default — `None` reads as `0`, so only an operator who sets a floor gets an early "budget, not input" `ADMISSION_BUDGET` refusal on top of the ledger's own hard stop at `max_cost`); count caps are an optional operator guard that ignores referees; referees run in `referee_slots` of `max_concurrency`. RUN_PLAN.md: mark the `max_total_tasks = 1 + referee allowance` arithmetic "S1 only". `run-plan.example.json`: add `"referee_slots": 2`. Rewrite `tests/test_commons_review.py::test_request_review_is_admitted_like_recruitment` to assert a referee is admitted past a full task cap and refused on an operator-set dollar floor.
- [ ] **Step 6: Run the tests**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_society_admission.py tests/test_research_workforce.py tests/test_commons_review.py tests/test_society_tools.py tests/test_run_control.py tests/test_run_cli.py tests/test_research_budget_wait.py tests/test_network_postgres.py tests/test_society_simulation.py tests/test_joined_delegation.py tests/test_event_waits.py tests/test_swarm_coordination_gaps.py -q`
Expected: PASS. Run the whole society suite here, not a subset: with no default admission floor, this is where a stale assumption of an implicit floor would show up.

- [ ] **Step 7: Commit**

```bash
git add src/physharness docs/RESEARCH_NETWORK.md work/society-s1 tests/test_society_admission.py tests/test_commons_review.py
git -c user.name=Kieran -c user.email=88352982+zubadestroyer1@users.noreply.github.com commit -m "feat: admit society work by remaining dollars and give referees a slot pool" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 19: Declared routes, time boxes and a kill signal at choice points (#22)

**Files:**
- Modify: `src/physharness/commons_discourse.py:79-102` (`_active_claims` fields; route-aware `_live_claim_counts`), `:151-217` (`claim_node(..., *, route=None, time_box_minutes=None)`), `:219-235` (`_touch_node` caps at the box), `:450-466` (`_post_urgent` for `compiled_by`), new `_post_route_compiled`
- Modify: `src/physharness/commons_sources.py` (`record_lean_source` posts the kill note)
- Modify: `src/physharness/orchestration/society_tools.py:1186-1195` (`commons_claim` schema), `society_prompt.py` (`NORMS`)
- Modify: `PLAN.md` §2.3, §4.4; `docs/RESEARCH_NETWORK.md` (Claims bullet)
- Test: `tests/test_commons_discourse.py`

**Interfaces:**
- Consumes: `record_lean_source`, `COMPLETE_RANKS` (Task 9); Task 8's skip of non-urgent platform statuses.
- Produces: claim payload keys `route: str | None`, `claimed_at: float`, `time_box_until: float | None`; `_active_claims` items add `route`, `time_box_until`; claim results' `co_claimants` add `route`; a platform post with `platform_status = {"compiled_by": branch_id, "route": route}` that is urgent only for other live claimants. Several claims per node stay allowed; only undeclared or duplicate routes lower the frontier score.

- [ ] **Step 1: Write the failing tests** (`tests/test_commons_discourse.py`, using its `clock` fixture)

```python
def test_claims_carry_a_route_and_a_time_box_that_caps_renewal(lab, clock):
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    node = service.create_node(exp["id"], NodeCreate(node_type="lemma", title="L", statement="L."), alpha, "l")
    claimed = service.claim_node(node["id"], "claim", beta, "c", route="Banach fixed point", time_box_minutes=5)
    assert claimed["route"] == "Banach fixed point" and claimed["time_box_until"] == clock.now + 300
    clock.now += 240
    service.post_on_node(node["id"], NodePostCreate(kind="finding", abstract="Progress."), beta, "p")
    [claim] = [c for c in service.read_node(node["id"], alpha)["claimants"] if c["branch_id"] == beta.branch_id]
    assert claim["expires_at"] == clock.now + 60 and claim["route"] == "Banach fixed point"
    clock.now += 61
    assert all(c["branch_id"] != beta.branch_id for c in service.read_node(node["id"], alpha)["claimants"])

def test_distinct_routes_keep_the_frontier_score(lab):
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    node = service.create_node(exp["id"], NodeCreate(node_type="lemma", title="L", statement="L."), alpha, "l")

    def penalty():
        items = service.query_nodes(exp["id"], alpha, frontier=True)["items"]
        return next(i for i in items if i["id"] == node["id"])["score_components"]["claimants"]

    service.claim_node(node["id"], "claim", alpha, "a", route="linear algebra")
    service.claim_node(node["id"], "claim", beta, "b", route="Banach")
    assert penalty() == 0.0
    service.claim_node(node["id"], "claim", beta, "b2", route="Linear  Algebra")
    assert penalty() == -2.0
```

  Also (specified): `test_a_compiled_route_is_urgent_for_other_claimants_only` (beta claims alpha's node with route "B"; alpha publishes a `complete` source through `record_lean_source`; beta's `discussion_updates` has an urgent item whose excerpt contains "compiled by" and "consider stopping your route"; alpha gets none); `test_time_box_is_bounded` (`time_box_minutes=4` or `241` → `INVALID_CLAIM`, 422; a route over 200 characters likewise).
- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_commons_discourse.py -q -k "route or time_box or compiled"`
Expected: FAIL.

- [ ] **Step 3: Implement**
  - `claim_node(node_id, action, actor, key, *, route=None, time_box_minutes=None)`: a route is stripped text of 1–200 characters and a time box an int of 5–240 (else `INVALID_CLAIM`, 422); both go into the command inputs. `claim` stores `route`, `claimed_at = now` and `time_box_until = now + 60 * time_box_minutes` (or `None`); `renew` keeps them. Every expiry, in `claim_node` and `_touch_node`, is `min(now + ttl, time_box_until)` when a box is set. `co_claimants` include `route`.
  - `_active_claims` returns `route` and `time_box_until` via `.get` (stored S1 claims lack them). `_live_claim_counts` returns, per node, the number of live claims whose normalized route (`" ".join(route.casefold().split())`) is missing or held by another live claim of the node.
  - `_post_route_compiled(session, row, branch_id, route, op)` inserts a platform `update` post (abstract `f"Node {row.id[:8]} compiled by {branch_id[:8]}" + (f" (route: {route})" if route else "") + "; consider stopping your route."`) with `platform_status={"compiled_by": branch_id, "route": route}`; `_post_urgent` returns, for such a post, whether the reader holds a live claim on the node and is not `compiled_by`. `record_lean_source` calls it when the new effective rank is in `COMPLETE_RANKS` and the previous one was not, passing the publisher's own claim route.
  - `commons_claim` schema adds `"route": text(200, "claim: the method you are trying, when several routes exist.", nullable=True)` and `"time_box_minutes": integer(5, 240, "claim: when your claim lapses unless you re-claim.", nullable=True)` (defaults `None`), passed through to `claim_node`.
  - `NORMS[2]` becomes `"Claim the node you work on before sinking effort (the goal takes none; read its thread on demand). Several branches may claim one node on different routes: name yours, and optionally a time box."` and add `"At a genuine choice between methods, a second route is cheap insurance; stop yours when another compiles."` (update `tests/test_society_scaffolding.py`).
- [ ] **Step 4: Docs.** PLAN.md §2.3: routes and time boxes; the frontier rewards distinct routes; the kill note. §4.4: "Declared alternative routes at genuine choice points, with time boxes and the compile note, replace labs as the diversity mechanism." RESEARCH_NETWORK Claims bullet likewise.
- [ ] **Step 5: Run the tests**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_commons_discourse.py tests/test_commons_sources.py tests/test_relevance_routing.py tests/test_event_waits.py tests/test_society_tools.py tests/test_society_scaffolding.py tests/test_commons_postgresql.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/physharness docs/RESEARCH_NETWORK.md PLAN.md tests
git -c user.name=Kieran -c user.email=88352982+zubadestroyer1@users.noreply.github.com commit -m "feat: let claims declare routes and time boxes, and tell co-claimants when a route compiles" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 20: Library notes per Mathlib pin (#24)

**Files:**
- Modify: `src/physharness/storage.py` (`LibraryNoteRow` after `EdgeRow`)
- Create: `migrations/versions/0004_library_notes.py`, `src/physharness/library_notes.py` (`LibraryNotesMixin`, `seed_notes`), `src/physharness/knowledge/library_notes_seed.json`
- Modify: `src/physharness/service.py:116-125` (mixin), `src/physharness/orchestration/society_tools.py` (`library_notes` tool after `notebook`; `find_declaration` wrapper; `SOCIETY_TOOL_NAMES`), `society_prompt.py` (`constitution` pointer line)
- Modify: `tools/society_metrics.py` (`OTHER` adds `library_notes`), `src/physharness/execution/stagnation.py` (`NON_PROGRESS_TOOLS` adds `library_notes`), `work/society-s1/RUN_PLAN.md` §7 (`other` list), `docs/RESEARCH_NETWORK.md`, `PLAN.md` §3.2
- Test: create `tests/test_library_notes.py`; `tests/test_infrastructure.py:28-38,98-120`; `tests/test_commons_postgresql.py`; `tests/test_society_tools.py::test_society_catalog_without_literature_or_review` (add `library_notes` to the bare catalog's expected tool list)

**Interfaces:**
- Consumes: `WorkspaceTools.find_declaration` (Task 13), `knowledge.index.tokens`.
- Produces: table `library_notes(id, project_id, environment_digest, experiment_id, author, text, created_at)` with index `library_notes_project_environment (project_id, environment_digest, created_at)`; `library_notes.MAX_NOTE_CHARS = 2000`, `MAX_NOTES_PER_ENVIRONMENT = 200`, `SEED_AUTHOR = "seed:S1 audit 2026-09-26"`, `seed_notes(environment_digest) -> list[str]`; `LibraryNotesMixin.library_notes(actor, *, query=None, limit=20) -> {"environment_digest", "notes": [{"id"?, "text", "author", "created_at"}]}` and `append_library_note(text, actor, key) -> {"id", "environment_digest", "text"}`; errors `INVALID_NOTE` (422), `LIBRARY_NOTES_FULL`; tool `library_notes(action=read|append, query, text)`; `find_declaration` results gain `library_notes: list[str]` (at most 2) when not exact.

- [ ] **Step 1: Write the failing tests** (`tests/test_library_notes.py`)

```python
import pytest
from commons_helpers import society_lab

from physharness import library_notes as notes_module
from physharness.domain import new_id
from physharness.errors import HarnessError
from physharness.storage import LibraryNoteRow

S1_DIGEST = "0c46de2450bd5a9b2584d513d3ad02a963a300c3b0e3510a3a22efbc5a11341f"
NOTE = "`Foo.bar` was renamed `Foo.baz` at this pin."

def other_row(project_id, digest, text):
    return LibraryNoteRow(id=new_id(), project_id=project_id, environment_digest=digest, experiment_id="x",
                          author="branch:x", text=text, created_at="2026-09-26T00:00:00+00:00")

def test_notes_are_project_and_pin_scoped_idempotent_and_seeded(lab, monkeypatch):
    service, _, exp, _, (alpha, beta) = society_lab(lab)
    appended = service.append_library_note(NOTE, alpha, "n1")
    assert service.append_library_note(NOTE, alpha, "n1") == appended
    found = service.library_notes(beta, query="Foo.bar")
    assert [(n["text"], n["author"]) for n in found["notes"]] == [(NOTE, f"branch:{alpha.branch_id}")]
    with service.db.transaction() as session:
        session.add(other_row("other-project", found["environment_digest"], "Foo.bar elsewhere"))
        session.add(other_row("lab", "f" * 64, "Foo.bar on another pin"))
    assert [n["text"] for n in service.library_notes(beta, query="Foo.bar")["notes"]] == [NOTE]
    monkeypatch.setattr(notes_module, "seed_notes", lambda digest: ["A seeded fact about Foo.bar."])
    assert service.library_notes(beta, query="Foo.bar")["notes"][0]["author"] == notes_module.SEED_AUTHOR
    with pytest.raises(HarnessError) as long:
        service.append_library_note("x" * 2001, alpha, "long")
    assert long.value.code == "INVALID_NOTE"

def test_the_checked_in_seed_covers_the_s1_audit_findings():
    seeded = " ".join(notes_module.seed_notes(S1_DIGEST))
    assert "Matrix.dotProduct" in seeded and "Perron" in seeded and len(seeded) < 3 * 2000
```

  `tests/test_infrastructure.py`: add `"library_notes"` to the table set of `test_migration_creates_real_schema_and_can_revert` and `assert "CREATE TABLE library_notes" in sql` to `test_postgresql_offline_migration_generates_real_sql` (the frozen-contract test then compares columns and index DDL automatically). `tests/test_commons_postgresql.py`: `test_library_notes_on_the_backend(backend_lab)` appends, re-appends with the same key, and reads with a query on SQLite and, when `PHYSHARNESS_TEST_DATABASE_URL` is set, PostgreSQL. `tests/test_society_tools.py` (specified): a non-exact `find_declaration` (`FakeWorkspace.find_declaration` returning `{"rows": [], "exact": False}`) after an appended note about `Matrix.dotProduct` returns that note under `library_notes`; the constitution holds exactly one line starting "Library notes:" and no note text.
- [ ] **Step 2: Run them to verify they fail**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_library_notes.py tests/test_infrastructure.py -q`
Expected: FAIL (no table, no mixin).

- [ ] **Step 3: Table and migration.** `storage.py`:

```python
class LibraryNoteRow(Base):
    """Agent-written facts about one pinned Lean/Mathlib environment, shared by a project's
    experiments (S1 audit #24): the one table the S1 remediation adds."""

    __tablename__ = "library_notes"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(200))
    environment_digest: Mapped[str] = mapped_column(String(64))
    experiment_id: Mapped[str] = mapped_column(String(36))
    author: Mapped[str] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(String(2000))
    created_at: Mapped[str] = mapped_column(String(40))
    __table_args__ = (
        Index("library_notes_project_environment", "project_id", "environment_digest", "created_at"),
    )
```

  `migrations/versions/0004_library_notes.py`:

```python
"""Project-scoped library notes per pinned Lean environment (S1 audit #24)."""

import sqlalchemy as sa
from alembic import op

revision = "0004_library_notes"
down_revision = "0003_discussion_indexes"
branch_labels = None
depends_on = None

def upgrade():
    op.create_table(
        "library_notes",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("project_id", sa.String(200), nullable=False),
        sa.Column("environment_digest", sa.String(64), nullable=False),
        sa.Column("experiment_id", sa.String(36), nullable=False),
        sa.Column("author", sa.String(200), nullable=False),
        sa.Column("text", sa.String(2000), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False),
    )
    op.create_index(
        "library_notes_project_environment",
        "library_notes",
        ["project_id", "environment_digest", "created_at"],
    )

def downgrade():
    op.drop_index("library_notes_project_environment", table_name="library_notes")
    op.drop_table("library_notes")
```

- [ ] **Step 4: Service** (`library_notes.py`, mixin added to `HarnessService`). The environment is the experiment problem's `environment_digest` (`_get(session, "experiment", actor.experiment_id, actor)`, then its problem). `seed_notes(digest)` loads `knowledge/library_notes_seed.json` once (`importlib.resources`, `functools.cache`) and returns its list for the digest, else `[]`. `library_notes` reads at most `MAX_NOTES_PER_ENVIRONMENT` rows for `(project_id, digest)`, newest first; seed notes come first with author `SEED_AUTHOR` and no `id`/`created_at`; with a `query`, keep notes sharing a `tokens(...)` token, ordered by overlap (seeds first on ties); return at most `limit`. `append_library_note` requires an agent with a branch, strips the text and requires 1–2,000 characters (`INVALID_NOTE`), runs under `self._execute(actor, key, "library_notes.append", {"text": text}, action)`; `action` takes `self.db.command_lock(session, self._digest(["library-notes", actor.project_id, digest]))`, refuses past 200 notes with `HarnessError("LIBRARY_NOTES_FULL", f"Library notes are full (budget, not input: limit 200, used {count}).", remediation="Read the existing notes; an operator prunes them.")`, adds the row (`author=f"branch:{actor.branch_id}"`), and emits `library_note.appended` with `{experiment_id, environment_digest}`.
- [ ] **Step 5: Seed** (`knowledge/library_notes_seed.json`; confirm the key with `grep -rl 0c46de2450bd5a9b work/hardening-final-2026-09-24/`):

```json
{
  "0c46de2450bd5a9b2584d513d3ad02a963a300c3b0e3510a3a22efbc5a11341f": [
    "`Matrix.dotProduct` is not a declaration at this pin (17 failed uses in S1): the dot product is the root-namespace `dotProduct`, notation `⬝ᵥ`. `Matrix.vecMul_mul` and `Matrix.vecMul_pow` also failed; look names up with find_declaration first.",
    "Perron–Frobenius and Brouwer/Schauder fixed-point theorems are absent at this pin: all 13 S1 arms searched and found none. What worked: the coin theorem `Nat.exists_add_mul_eq_of_gcd_dvd_of_mul_pred_le` (Mathlib/Algebra/Order/Ring/Int.lean) and Banach's fixed point `ContractingWith` on the ℓ¹ simplex as a `PiLp 1` subtype.",
    "`PiLp.toLp` and `PiLp.ofLp` failed 9 times in S1; the renamed API lives under `WithLp` (`WithLp.ofLp`). Check with find_declaration."
  ]
}
```

- [ ] **Step 6: Tool, pointer, search integration.** `library_notes` (builders only, after `notebook`; not in `REFEREE_TOOL_NAMES`): `{"action": choice(("read", "append"), "read the notes, or append one fact."), "query": text(200, "read: words to match (optional).", nullable=True), "text": text(2000, "append: one fact you checked in Lean (a rename, an absence, a working API).", nullable=True)}`, defaults `None`; `append` without `text` → `invalid(...)`; description "Shared notes about this pinned Mathlib/Physlib environment, kept across experiments: renamed APIs, known absences, working recipes. Read before guessing names; append a fact once you have checked it in Lean." Wrap `find_declaration`: after `workspace_tools.find_declaration(a, k)`, when a query was given and the result is not `exact`, add `library_notes = [n["text"] for n in service.library_notes(agent, query=a["query"], limit=2)["notes"]]` if non-empty. `constitution()` adds, after `BOUNDARIES`, the line `"Library notes: library_notes(action='read') holds shared facts about this Mathlib pin (renamed APIs, known absences); append one when you have checked it."` (not in `referee_constitution`).
- [ ] **Step 7: Docs.** RESEARCH_NETWORK: a Library notes bullet (scope: project and environment digest; 2,000 characters; 200 per pin; seeded from the S1 audit; surfaced by `find_declaration`). PLAN.md §3.2: "4. **Library notes.** Shared, per Mathlib pin, across a project's experiments." RUN_PLAN §7 `other` list: add `library_notes`.
- [ ] **Step 8: Run the tests**

Run: `PYTHONPATH=src .venv/bin/python -m pytest tests/test_library_notes.py tests/test_infrastructure.py tests/test_commons_postgresql.py tests/test_society_tools.py tests/test_society_metrics.py tests/test_society_scaffolding.py -q`
Expected: PASS (PostgreSQL cases skip without `PHYSHARNESS_TEST_DATABASE_URL`).

- [ ] **Step 9: Commit**

```bash
git add src/physharness/storage.py migrations/versions/0004_library_notes.py src/physharness/library_notes.py src/physharness/knowledge/library_notes_seed.json src/physharness/service.py src/physharness/orchestration/society_tools.py src/physharness/orchestration/society_prompt.py src/physharness/execution/stagnation.py tools/society_metrics.py work/society-s1/RUN_PLAN.md docs/RESEARCH_NETWORK.md PLAN.md tests
git -c user.name=Kieran -c user.email=88352982+zubadestroyer1@users.noreply.github.com commit -m "feat: add project-scoped library notes per Mathlib pin" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 21: Tool counts, a docs consistency pass, the full suite and ruff

**Files:**
- Modify: `tests/test_society_tools.py:442-470` (literal counts), `src/physharness/orchestration/society_tools.py:1-15` (module docstring)
- Modify: `PLAN.md` (§1–§11 as listed below), `docs/RESEARCH_NETWORK.md` (society section), `docs/IMPLEMENTATION_STATUS.md` (society status)

**Interfaces:**
- Consumes: the final catalog — `SOCIETY_TOOL_NAMES` = `shell, read_file, write_file, run_computation, lean_check, find_declaration, search_literature, fetch_source, commons_query, commons_read, read_artifact, commons_node, commons_post, commons_claim, commons_fetch, recruit, message, wait, submit_for_verification, verification_status, notebook, library_notes, return_result, submit_review` (24); `REFEREE_TOOL_NAMES` = `shell, read_file, write_file, run_computation, lean_check, find_declaration, search_literature, fetch_source, commons_query, commons_read, read_artifact, commons_post, verification_status, notebook, submit_review` (15).
- Produces: nothing new.

- [ ] **Step 1: The tool-count pass (once, per S11).** In `test_society_catalog_widest` assert `(len(SOCIETY_TOOL_NAMES), len(names(dispatcher)), len(REFEREE_TOOLS)) == (24, 23, 15)` and that both tuples equal the lists above in order. Module docstring: "Twenty-four tools replace the 63 legacy ones for experiments with a society policy." RESEARCH_NETWORK: "It has 24 tools in all; a worker's widest catalog has 23 (all but `submit_review`), and a referee's has 15", with the tool table regrouped (Lean `lean_check`; Library `find_declaration`, `library_notes`; Commons `commons_query`, `commons_read`, `commons_node`, `commons_post`, `commons_claim`, `commons_fetch`; Society `recruit`, `message`, `wait`; Memory `notebook`).
- [ ] **Step 2: Docs consistency.** Run `grep -n -i "lab\b\|labs\|lab_size\|ladder\|formally_stated\|compiles_locally\|fidelity\|inbox\|lean_sketch\|load_skill\|search_library\|read_source\|check-in\|nudge\|refereed" PLAN.md docs/RESEARCH_NETWORK.md docs/IMPLEMENTATION_STATUS.md` and make every society statement current, keeping S1-historical statements marked as such. In PLAN.md specifically: §1 decisions keep their date; §2.2 is "Status" (Task 12); §2.4 has no labs (Task 6); §3.1 norms equal `society_prompt.NORMS`; §3.3's heading becomes "(24 in the society profile, down from 63)" with the final table; §3.7 matches the playbook and has no check-ins, nudges or skills; §4.4 names routes (Task 19); §7 adds under the S1 row "**S1 remediation (2026-09-26):** Tier 0 fixes plus the society substrate (lemma store, relevance routing, event waits, library notes) replaced labs, the ladder, fidelity reviews, check-ins and count caps; evidence is deterministic tests"; §9 society health drops "fidelity-check failure rate" for new arms and adds reuse by provenance; §10 herding row as in Task 6.
- [ ] **Step 3: Scrub.** `git diff main --name-only | xargs grep -n -e "/Users/" -e "$(whoami)" || true` must print nothing (no absolute home paths, no local username).
- [ ] **Step 4: Full suite**

Run: `PYTHONPATH=src .venv/bin/python -m pytest -q`
Expected: PASS (opt-in real-image, real-Lean and PostgreSQL tests skip without their environment variables).

- [ ] **Step 5: Ruff**

Run: `.venv/bin/python -m ruff check src tests tools infra migrations && .venv/bin/python -m ruff format --check src tests tools infra migrations`
Expected: no findings. (Fix with `ruff format src tests tools infra migrations` and re-run the suite if it changed anything.)

- [ ] **Step 6: Commit**

```bash
git add PLAN.md docs/RESEARCH_NETWORK.md docs/IMPLEMENTATION_STATUS.md src/physharness/orchestration/society_tools.py tests/test_society_tools.py
git -c user.name=Kieran -c user.email=88352982+zubadestroyer1@users.noreply.github.com commit -m "docs: bring the plan and research-network docs in line with the remediated society" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

- [ ] **Step 7: PR notes (for the society PR body; not a committed file).** List the G6 next steps (#25 harder target; the paid A/B run, which needs a budget; #12d olean imports; warm-REPL reuse; the org TPM limit). List what the A/B must measure against S-r2: first-two-minute division of labour (the goal broadcast is gone), post-contribution spend, wake counts and reasons, messages refused by the rate limit, parallel routes opened at the long pole, recruit lifetime, cross-branch imports in the accepted proof (the modules it inlined, used or not: an upper bound on reuse, since nothing checks which constants the proof uses). Note that the audit extractor (`work/society-s1/audit-2026-09-26/scripts/extract.py`, `scripts/scaffold/composition.py`) must learn the compact update lines and the new prompt keys before comparing arms.

---

## Self-review

- **Spec coverage.** Tier 0 #1 (Task 1), #2 (Task 2), #3 and #5a–c (Task 3), #5d (Task 4); society #20 (5), #15 (6), #18 (7), #13 (8), #12a–c (9–11), #17 (12), #19 (13), #21 (14), #23 (15), #14 (16–17), #16 (18), #22 (19), #24 (20); the tool-count pass and docs (21). #4, #6–#11 and `ensure_ascii` in `responses.py` belong to the runtime lane; #12d and #25 are G6 next steps.
- **Names across tasks.** `resolve_id`/`_prefix_candidates`/`ident` (4 → 6, 9, 11, 16); `_refuse_removed` (5 → 6, 13); `_push_skip`/`_delivery_clauses` (8 → 16); `record_lean_source`, `node_module`, `source_state`, `COMPLETE_RANKS` (9 → 10–15, 19); `expand_commons`, `split_imports`, `Module` (10 → 11, 14); `public_status` (12); `find_declaration` (13 → 20); `COMPLETION_REASONS` (15); ticket `kind == "events"` under `peer_wait` (16 → 17).

---

## Controller rulings applied (2026-09-27)

- **F1.** Task 11 now appends its new norm instead of inserting it by index; Task 12 and Task 15 each edit their norm by matching its existing text ("Ask for a referee…", "Recruit when…") instead of by index.
- **F2.** Task 18 drops the `DEFAULT_ADMISSION_FLOOR_USD = "1.00"` default: `admission_floor_usd` is `None` by default, read as `0` (no floor unless an operator sets one); Step 6 now runs the whole society suite, including `test_society_simulation`, `test_joined_delegation`, `test_event_waits` and `test_swarm_coordination_gaps`.
- **F3.** Task 11's Files entry now says `commons_fetch` sits right after `commons_claim` in `SOCIETY_TOOL_NAMES`, matching Step 3's registration order (Task 21's final list was already in this order).
- **F4.** Task 7's prompt test now asserts `set(prompt["target"]) == set(society_brief.TARGET_FIELDS)`, since `canonical_json` sorts keys.
- **F5.** Task 1's `provisioning_tools` test helper now sets `cost_bound_usd=0` on its policy `SimpleNamespace`.
- **F6.** Task 17's `test_an_all_parked_society_stops_idle` and Task 18's `test_runner_reserves_referee_slots` now monkeypatch `continuation.EVENT_WAIT_MIN_SLEEP_SECONDS` to `0`/`1`, raise the manifest timeout above it, and build `TeamRunManifest` directly for their multiple roots instead of the single-root `run_manifest` helper.
- **F7.** No change: the plan's S10 already reads "Referees review plans only," matching the ruling.
- **F8.** Task 10's `verify_candidate` gains an internal-only `commons_modules=` keyword (not part of the API request body) that only `submit_for_verification`'s flattening step sets, from platform-resolved `expansion.modules`; Task 12's `_commons_goal_accepted` now reads `receipt.payload["commons_modules"]` instead of the artifact's caller-writable `provenance.commons`, and Task 12 gains `test_forged_artifact_provenance_does_not_accept_unused_nodes`.
- **F9.** Task 8's `test_non_urgent_platform_status_is_skipped_but_urgent_is_delivered` spec now accepts via the legal transition `set_status(..., "formally_stated", "accepted")`.
- **F10.** Task 18 adds a `concurrency=` pass-through to the `society_lab` fixture (defaulting to today's value, 2) and its referee-slot test now requests `concurrency=3`.
- **F11.** No change (accepted).
- **F12.** No change (accepted).
- **F13.** Task 13's guest script gains a `MAX_INDEX_BYTES` (64 MiB) cap with a `declaration_index_failed`/`rg` remediation past it, plus a real-`physharness-pilot`-container timed run (reusing Task 2 Step 5's protocol, now named as G7's other permitted Docker use) with a lazy, `rg`-backed, 20-row-capped fallback if that run exceeds 60 s or the cap; Task 2 Step 5 and G7 cross-reference this.
- **F14.** No change (accepted).
- **F15.** Task 18's Interfaces bullet now says legacy experiments keep today's count caps and Task 3's error-message wording (not "today's messages"), since G1 covers prompts and freeze tests, not error text.
- **F16.** Task 1's docs step now also notes the checker persists under `/work/.physharness` into checkpoints and handoff archives, and that a handoff-restored workspace skips the self-test.
- **F17.** Task 9 now also modifies `memory.py`'s `working_context` to skip a `lean_source` artifact whose `provenance` has a `node_id` when picking the branch's active-source candidate, with a new test in `tests/test_memory.py`.
- **F18.** Task 12's Step 7 now updates `test_goal_accepted_hook_on_verified_target_receipt`'s goal-status assertion to `"open"`; Task 13's Step 7 now updates `test_society_catalog_without_literature_or_review` to drop `ScaffoldingPolicy(skills=False)` and `inbox`; Task 20 now also adds `library_notes` to that same bare-catalog test.
- **F19.** Task 9's `commons.source_published` event now explicitly sets `aggregate_id = node_id`.
- **F20.** Task 16's long-pole fallback now requires at least one open dependent before it applies, falling back to the static hint otherwise, and notes that the prompt and the compaction anchor share the same `query_nodes(frontier=True)["long_pole"]` computation.
- **F21.** Fixed stale line refs: Task 8's and Task 15's `responses.py` refs (`:301-367`, `:1142-1168`), Task 17's wake-note ref (`:1848-1851`), Task 18's `research_capacity` ref (`:950`), Task 11's `_source_provenance` ref (now described as new code beside `compute_metrics`, not at its location), and Task 4's Interfaces claim about Task 20 declaring ids with `ident` (removed; `library_notes` has no id property).
- **F22.** No change (accepted).
- **F23.** Added to the plan's Merge note: the runtime lane's `recall_output` stays out of `SOCIETY_TOOL_NAMES` and opt-in on `context_budget`, and its checkpoint slimming keeps `native_state["input"]` intact.
