# Branch visibility and collaboration

Research workers receive a server-created `Principal` with both `experiment_id` and `branch_id`. These are trusted identity assignments, not model tool arguments. Each delegated branch receives a new execution identity; each task execution receives a fresh worker identity under that same experiment and its existing resource envelope. Creating a child never increases its budget.

`Experiment.sharing` governs actual record reads, artifact bytes, paginated listings, restart briefs, events, and messages. Operators and reviewers retain their canonical project access.

| Policy | Worker visibility across branches | Free-text messages |
| --- | --- | --- |
| `none` | Own branch and explicitly supplied trusted inputs only | Within the same branch only |
| `verified` | Additionally, accepted candidate artifacts and their canonical verified receipts/claims | Within the same branch only; accepted evidence is discovered through reads |
| `ideas` | Additionally, attributed research artifacts, proposed claims, sources and programs | Attributed messages to another branch in the experiment |

All workers can read their assigned target, assumptions, campaign, and experiment envelope. A parent may inspect the child branch it created and schedule tasks there. This narrow delegation permission does not expose the child's results or native history. Independent branches cannot schedule work as another branch or impersonate a message sender. Explicit delegation objectives can carry the parent's chosen context; parent history is never automatically copied into a child's brief.

Even `ideas` keeps other branches' native sessions, native checkpoints, branch checkpoints, runtime events, and failure artifacts private. Messages are visible to their sender and recipient, rather than becoming a project-wide mailbox. Artifact attribution is stored separately from evidence status; an idea, completed task, or successfully delivered message never establishes proof or publication status.

## Canonical ownership and inputs

`ArtifactCreate.branch_id` assigns a trusted controller's output to a branch. Worker submissions automatically receive their identity's branch; conflicting branch fields or provenance are rejected. New records store a server-written `origin_actor_id`. Receipts, accepted claims, sessions, sources, programs, and controller-created runtime artifacts inherit canonical branch association from their validated task or source references. A provenance dictionary or receipt-shaped artifact cannot grant verification or visibility.

To supply a common input, a trusted researcher/operator can create an artifact with `trusted_input=True`. Agents cannot set this flag. Ordinary unscoped artifacts are not automatically common inputs. Old records with only an unvalidated provenance branch are not silently reclassified as branch-owned; a controller must explicitly supply suitably scoped records when resuming old work.

Cross-branch verified evidence requires a canonical verification record with `status=verified`, `assurance=independent_kernel`, matching experiment, reviewed problem revision, exact target and environment digests, and the candidate artifact's content hash. Canonical verified claims must link back to that receipt. A proposed claim or user-provided `verified` label does not satisfy this predicate. Artifact content reads still perform the existing content-store integrity check. This visibility gate does not change scientific acceptance or publication requirements.

## Controllers, checkpoints and compatibility

An experiment-only legacy agent retains access to its own authored submissions and trusted inputs. It does not receive experiment-wide scientific results. An explicitly assigned `agent_orchestrator=True` identity may inspect branch/task topology and schedule work; it still cannot inspect other workers' private artifacts. This capability must never be assigned to a branch worker. Trusted operator/reviewer identities retain their existing broader record access.

Idempotency fingerprints include role, experiment, branch, and orchestrator authority. Reusing a command after reassignment fails rather than returning a cached response from an earlier authority scope.

Worker runtime outputs, events, and native session records carry their task's branch. Native checkpoint loading and saving are task-bound. Even when an operator creates a branch checkpoint, its embedded brief is generated with that branch's restricted worker identity, and any native artifact must be readable in that scope. Inspecting a canonical checkpoint as an operator does not grant the destination worker other branches' history.

Knowledge retrieval must apply the same visibility gate when its trusted broker accesses claims from the consuming experiment. Cross-experiment knowledge eligibility remains the research information policy's responsibility. The API/authentication layer must construct branch assignments from trusted credentials; accepting a model-supplied identity would bypass the service's trust boundary.

## Validation and limits

`tests/test_sharing.py` exercises direct reads and bytes, pagination, restart briefs, event visibility, cross-branch mail restrictions, sender and provenance forgery, canonical acceptance bindings, explicit orchestrators, nested delegation, controller checkpoint history, actual worker prompt/tool construction, and native session/task binding. Accepted-receipt fixtures are controlled database records for authorization testing. Worker tests use scripted protocol runtimes. Neither provides live proof-checker qualification, containment evidence, live model results, or evidence that collaboration improves scientific success.

## Executing a finite team

`ResearchTeamRunner` takes an explicit list of root task IDs and can discover delegated tasks
under their descendant branches. Helpers, collaborators, and competing approaches have the
same canonical execution and budgeting rules; the relation expresses the model's intended
collaboration pattern. Each task's dependency IDs determine when it may start. A child without
a dependency on its parent can finish after that parent's model request fails.

A finite run stores its manifest and result as canonical artifacts and reports unfinished
tasks when its concurrency, task-count, verification-count, or time limits prevent further
progress. Individual tasks, checkpoints, messages, receipts, and unsettled reservations survive
the supervisor. Recovery never infers that a lost request was free or reuses a parent's lease.

Model tools are transactionally bound to the assigned holder and fence. Losing the lease or
cancelling the experiment prevents further worker effects, including replay of old cached
commands. Portable context checkpoints retain exact target assumptions, unresolved obligations,
and unverified summary attribution over repeated compactions. They do not carry native model
history to a child. If canonical obligations or review change, restoration requires a fresh
context from the canonical records.

The deterministic demonstrations in `tests/test_research_loop_integration.py` run the actual
OpenAI SDK with an explicit mock HTTP transport through real service/database/artifact and
ledger paths. They demonstrate single-worker completion, two overlapping workers, a surviving
delegated helper, continuation exclusion, cancellation, and bounded verification waiting.
A separate test injects a synthetic checker at the verifier boundary, obtains receipts through
`process_verification`, and retrieves the accepted dependency bundle. That fixture is explicitly
mock evidence and provides no live kernel, model, scientific-review, or publication qualification.
