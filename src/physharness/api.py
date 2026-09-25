"""Versioned private laboratory API; all state changes use application authority."""

import logging
import secrets
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import text
from starlette.exceptions import HTTPException

from . import __version__
from .config import Settings
from .discussion_models import DiscussionCreate, DiscussionPostCreate
from .domain import (
    ArtifactCreate,
    BranchCreate,
    CampaignCreate,
    ExperimentCreate,
    Principal,
    ProblemCreate,
    StrictModel,
    TaskCreate,
    new_id,
)
from .errors import HarnessError
from .logging import configure_logging
from .service import HarnessService
from .workforce_models import (
    ConfigureWorkforceRequest,
    JoinResearchTeamRequest,
    PublishResearchProfileRequest,
    RecruitResearcherRequest,
    RequestResearchCapacityRequest,
    SeedPortfolioRequest,
)

log = logging.getLogger(__name__)


class TransitionInput(StrictModel):
    action: Literal["start", "pause", "resume", "cancel"]
    expected_revision: int = Field(ge=1)


class ReviewInput(StrictModel):
    decision: Literal["approved", "rejected"]
    rationale: str = Field(min_length=1, max_length=20000)


class ClaimInput(StrictModel):
    statement: str = Field(min_length=1, max_length=100000)
    assumptions: list[str] = Field(default_factory=list)
    evidence: Literal["conjecture", "numerical", "conditional"]
    artifact_id: str | None = None


class VerifyInput(StrictModel):
    artifact_id: str
    publication: bool = False


class CandidateSourceInput(StrictModel):
    source: str = Field(min_length=1, max_length=5_000_000)


class SourceInput(StrictModel):
    experiment_id: str
    text: str = Field(min_length=1, max_length=2_000_000)
    format: Literal["markdown", "latex"]
    uri: str = Field(min_length=1, max_length=4096)
    source_revision: str = Field(min_length=1, max_length=256)
    license: str = Field(min_length=1, max_length=1000)


class ProgramInput(StrictModel):
    experiment_id: str
    source_artifact_id: str
    inputs: dict = Field(default_factory=dict)
    parent_id: str | None = None


class MessageInput(StrictModel):
    branch_id: str
    recipient_id: str
    content: str = Field(min_length=1, max_length=20000)
    artifact_ids: list[str] = Field(default_factory=list, max_length=100)


class ContextInput(StrictModel):
    approach: str = Field(min_length=1, max_length=100000)
    unresolved_obligations: list[str] = Field(max_length=1000)
    summary: str | None = Field(default=None, max_length=100000)
    previous_checkpoint_id: str | None = None
    evidence_ids: list[str] = Field(default_factory=list, max_length=1000)
    max_bytes: int = Field(default=65536, ge=1, le=8_388_608)
    max_estimated_tokens: int = Field(default=16384, ge=1, le=8_388_608)


class ResearchNotesInput(StrictModel):
    approach: str = Field(min_length=1, max_length=8192)
    unresolved_obligations: list[str] = Field(max_length=100)
    summary: str | None = Field(default=None, max_length=8192)
    evidence_ids: list[str] = Field(default_factory=list, max_length=100)
    task_id: str | None = None
    holder: str | None = None
    fence: int | None = None
    max_bytes: int = Field(default=8192, ge=1, le=65536)


class DiscussionSubscriptionInput(StrictModel):
    subscribed: bool


def create_app(settings: Settings | None = None, service: HarnessService | None = None) -> FastAPI:
    settings = settings or Settings()
    configure_logging(settings=settings)
    if service is None:
        from .bootstrap import build_service

        service = build_service(settings)
    app = FastAPI(title="PhysHarnessV2", version=__version__)
    app.state.service = service
    app.state.settings = settings
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Idempotency-Key", "Content-Type"],
        expose_headers=["X-Operation-ID"],
    )

    @app.middleware("http")
    async def correlate(request: Request, call_next):
        request.state.operation_id = new_id()
        response = await call_next(request)
        response.headers.setdefault("X-Operation-ID", request.state.operation_id)
        return response

    @app.exception_handler(HarnessError)
    async def harness_error(request: Request, error: HarnessError):
        if not error.operation_id:
            error.operation_id = request.state.operation_id
        log.warning(
            error.message, extra={"error_code": error.code, "operation_id": error.operation_id}
        )
        return JSONResponse(
            error.envelope(),
            status_code=error.status,
            headers={"X-Operation-ID": error.operation_id},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        fields = [{"location": list(e["loc"]), "type": e["type"]} for e in error.errors()]
        failure = HarnessError(
            "VALIDATION_ERROR",
            "The request does not match the API contract.",
            status=422,
            operation_id=request.state.operation_id,
            details={"fields": fields},
            remediation=(
                "Correct the listed fields; unknown and authority-bearing fields are rejected."
            ),
        )
        return JSONResponse(failure.envelope(), status_code=422)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, error: HTTPException):
        failure = HarnessError(
            "HTTP_ERROR",
            "The requested API operation is unavailable.",
            status=error.status_code,
            operation_id=request.state.operation_id,
        )
        return JSONResponse(failure.envelope(), status_code=error.status_code)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, error: Exception):
        operation_id = getattr(request.state, "operation_id", new_id())
        log.exception(
            "Unhandled API failure",
            exc_info=error,
            extra={"operation_id": operation_id, "error_code": "INTERNAL_ERROR"},
        )
        failure = HarnessError(
            "INTERNAL_ERROR",
            "The operation failed inside the service.",
            status=500,
            operation_id=operation_id,
            remediation=(
                "Inspect server logs using this operation ID; do not treat "
                "the operation as successful."
            ),
        )
        return JSONResponse(
            failure.envelope(), status_code=500, headers={"X-Operation-ID": operation_id}
        )

    def identity(authorization: Annotated[str | None, Header()] = None) -> Principal:
        if authorization and authorization.startswith("Bearer "):
            supplied = authorization[7:]
            for token, principal in settings.auth_tokens.items():
                if secrets.compare_digest(supplied.encode(), token.encode()):
                    return principal
        raise HarnessError(
            "UNAUTHENTICATED",
            "A valid project-scoped bearer token is required.",
            status=401,
            remediation="Configure an operator-issued identity and reconnect.",
        )

    def command_key(idempotency_key: Annotated[str | None, Header()] = None) -> str:
        if not idempotency_key:
            raise HarnessError(
                "IDEMPOTENCY_KEY_REQUIRED",
                "Mutations require an Idempotency-Key header.",
                status=422,
            )
        return idempotency_key

    Actor = Annotated[Principal, Depends(identity)]
    Key = Annotated[str, Depends(command_key)]

    @app.get("/healthz")
    def health():
        return {"status": "alive", "version": __version__}

    @app.get("/v1/status")
    def status(actor: Actor):
        checks = [
            {
                "name": "api",
                "status": "healthy",
                "detail": "Authenticated control API is responding.",
            }
        ]
        try:
            with service.db.sessions() as session:
                session.execute(text("SELECT 1 FROM records LIMIT 1"))
            checks.append(
                {
                    "name": "database",
                    "status": "healthy",
                    "detail": "Canonical record schema is accessible.",
                }
            )
        except Exception:
            log.exception("Database status probe failed")
            checks.append(
                {
                    "name": "database",
                    "status": "unavailable",
                    "detail": "Database/schema probe failed; run migrations and inspect logs.",
                }
            )
        checks.extend(
            [
                {
                    "name": "verification",
                    "status": "unavailable" if service.verifier is None else "configured",
                    "detail": (
                        "A configured verifier is not evidence of successful kernel qualification."
                    ),
                },
                {
                    "name": "temporal",
                    "status": "configured" if settings.temporal_address else "unavailable",
                    "detail": (
                        "Live workflow connectivity has not been qualified by this status probe."
                    ),
                },
                {
                    "name": "vm_workers",
                    "status": "unqualified",
                    "detail": "Live VM execution and recovery require provider qualification.",
                },
            ]
        )
        return {
            "version": __version__,
            "mode": settings.mode,
            "checks": checks,
            "qualifications": [
                {
                    "wave": i,
                    "status": "unqualified",
                    "detail": "See the implementation evidence ledger for completed local checks.",
                }
                for i in range(12)
            ],
        }

    def collection(kind):
        def endpoint(
            actor: Actor,
            experiment_id: str | None = None,
            limit: int = Query(default=500, ge=1, le=5000),
            after: str | None = None,
        ):
            return service.page_records(kind, actor, experiment_id, limit, after)

        return endpoint

    def detail(kind):
        def endpoint(identifier: str, actor: Actor):
            return service.get_record(kind, identifier, actor)

        return endpoint

    for plural, kind in {
        "campaigns": "campaign",
        "problems": "problem",
        "experiments": "experiment",
        "branches": "branch",
        "tasks": "task",
        "claims": "claim",
        "artifacts": "artifact",
        "reviews": "review",
        "sessions": "session",
        "programs": "program",
        "verifications": "verification",
        "messages": "message",
        "sources": "source",
        "workspaces": "workspace",
    }.items():
        app.add_api_route(f"/v1/{plural}", collection(kind), methods=["GET"], name=f"list_{plural}")
        app.add_api_route(
            f"/v1/{plural}/{{identifier}}", detail(kind), methods=["GET"], name=f"get_{kind}"
        )

    @app.post("/v1/campaigns", status_code=201)
    def create_campaign(body: CampaignCreate, actor: Actor, key: Key):
        return service.create_campaign(body, actor, key)

    @app.post("/v1/problems", status_code=201)
    def create_problem(body: ProblemCreate, actor: Actor, key: Key):
        return service.create_problem(body, actor, key)

    @app.post("/v1/experiments", status_code=201)
    def create_experiment(body: ExperimentCreate, actor: Actor, key: Key):
        return service.create_experiment(body, actor, key)

    @app.post("/v1/experiments/{identifier}/transition")
    def transition(identifier: str, body: TransitionInput, actor: Actor, key: Key):
        return service.transition_experiment(
            identifier, body.action, body.expected_revision, actor, key
        )

    @app.post("/v1/problems/{identifier}/reviews", status_code=201)
    def review(identifier: str, body: ReviewInput, actor: Actor, key: Key):
        return service.review_problem(identifier, body.decision, body.rationale, actor, key)

    @app.get("/v1/experiments/{identifier}/ledger")
    def ledger(identifier: str, actor: Actor):
        return service.ledger(identifier, actor)

    @app.post("/v1/experiments/{identifier}/workforce")
    def configure_workforce(
        identifier: str, body: ConfigureWorkforceRequest, actor: Actor, key: Key
    ):
        return service.configure_workforce(identifier, body, actor, key)

    @app.post("/v1/experiments/{identifier}/portfolio", status_code=201)
    def seed_portfolio(identifier: str, body: SeedPortfolioRequest, actor: Actor, key: Key):
        return service.seed_portfolio(identifier, body, actor, key)

    @app.post("/v1/experiments/{identifier}/recruit", status_code=201)
    def recruit_researcher(identifier: str, body: RecruitResearcherRequest, actor: Actor, key: Key):
        return service.recruit_researcher(identifier, body, actor, key)

    @app.post("/v1/experiments/{identifier}/research-profile")
    def publish_research_profile(
        identifier: str, body: PublishResearchProfileRequest, actor: Actor, key: Key
    ):
        return service.publish_research_profile(identifier, body, actor, key)

    @app.get("/v1/experiments/{identifier}/research-directory")
    def research_directory(
        identifier: str,
        actor: Actor,
        after: str | None = None,
        limit: int = Query(default=20, ge=1, le=20),
    ):
        return service.research_directory(identifier, actor, after=after, limit=limit)

    @app.post("/v1/experiments/{identifier}/research-team")
    def join_research_team(identifier: str, body: JoinResearchTeamRequest, actor: Actor, key: Key):
        return service.join_research_team(identifier, body, actor, key)

    @app.get("/v1/experiments/{identifier}/research-capacity")
    def research_capacity(identifier: str, actor: Actor):
        return service.research_capacity(identifier, actor)

    @app.post("/v1/experiments/{identifier}/research-capacity-requests")
    def request_research_capacity(
        identifier: str, body: RequestResearchCapacityRequest, actor: Actor, key: Key
    ):
        return service.request_research_capacity(identifier, body, actor, key)

    @app.post("/v1/experiments/{identifier}/schedule-synthesis")
    def schedule_research_synthesis(identifier: str, actor: Actor, key: Key):
        return service.schedule_research_synthesis(identifier, actor, key)

    @app.post("/v1/experiments/{identifier}/discussions", status_code=201)
    def create_discussion(identifier: str, body: DiscussionCreate, actor: Actor, key: Key):
        return service.create_discussion(identifier, body, actor, key)

    @app.get("/v1/experiments/{identifier}/discussions")
    def discussion_page(
        identifier: str,
        actor: Actor,
        after: int | None = Query(default=None, ge=0),
        limit: int = Query(default=20, ge=1, le=20),
    ):
        return service.discussion_page(identifier, actor, after=after, limit=limit)

    @app.post("/v1/discussions/{topic_id}/posts", status_code=201)
    def post_discussion(topic_id: str, body: DiscussionPostCreate, actor: Actor, key: Key):
        return service.post_discussion(topic_id, body, actor, key)

    @app.get("/v1/discussions/{topic_id}/posts")
    def discussion_posts(
        topic_id: str,
        actor: Actor,
        after: int | None = Query(default=None, ge=0),
        limit: int = Query(default=20, ge=1, le=20),
    ):
        return service.discussion_posts(topic_id, actor, after=after, limit=limit)

    @app.get("/v1/discussion-posts/{post_id}")
    def read_discussion_post(post_id: str, actor: Actor):
        return service.read_discussion_post(post_id, actor)

    @app.get("/v1/research-messages/{message_id}")
    def read_research_message(message_id: str, actor: Actor):
        return service.read_research_message(message_id, actor)

    @app.post("/v1/discussions/{topic_id}/subscription")
    def subscribe_discussion(
        topic_id: str, body: DiscussionSubscriptionInput, actor: Actor, key: Key
    ):
        return service.subscribe_discussion(topic_id, body.subscribed, actor, key)

    @app.get("/v1/experiments/{identifier}/discussion-updates")
    def discussion_updates(
        identifier: str,
        actor: Actor,
        after: int | None = Query(default=None, ge=0),
        limit: int = Query(default=10, ge=1, le=10),
    ):
        return service.discussion_updates(identifier, actor, after=after, limit=limit)

    @app.post("/v1/experiments/{identifier}/discussion-updates/{delivery_id}/ack")
    def acknowledge_discussion_updates(identifier: str, delivery_id: str, actor: Actor, key: Key):
        return service.acknowledge_discussion_updates(identifier, delivery_id, actor, key)

    @app.post("/v1/experiments/{identifier}/branches", status_code=201)
    def branch(identifier: str, body: BranchCreate, actor: Actor, key: Key):
        return service.create_branch(identifier, body, actor, key)

    @app.post("/v1/experiments/{identifier}/claims", status_code=201)
    def claim(identifier: str, body: ClaimInput, actor: Actor, key: Key):
        return service.create_claim(
            identifier,
            body.statement,
            body.assumptions,
            body.evidence,
            body.artifact_id,
            actor,
            key,
        )

    @app.post("/v1/artifacts", status_code=201)
    def artifact(body: ArtifactCreate, actor: Actor, key: Key):
        return service.create_artifact(body, actor, key)

    @app.get("/v1/artifacts/{identifier}/content")
    def artifact_content(identifier: str, actor: Actor):
        return {"content": service.artifact_content(identifier, actor).decode("utf-8")}

    @app.post("/v1/experiments/{identifier}/verify")
    def verify(identifier: str, body: VerifyInput, actor: Actor, key: Key):
        return service.verify_candidate(identifier, body.artifact_id, body.publication, actor, key)

    @app.get("/v1/events")
    def events(
        actor: Actor,
        after: int = Query(default=0, ge=0),
        limit: int = Query(default=100, ge=1, le=1000),
        tail: bool = False,
    ):
        return service.event_page(actor, after, limit, tail)

    @app.get("/v1/experiments/{identifier}/export")
    def export(identifier: str, actor: Actor):
        return service.export_experiment(identifier, actor)

    @app.post("/v1/tasks", status_code=201)
    def create_task(body: TaskCreate, actor: Actor, key: Key):
        return service.create_task(body, actor, key)

    @app.get("/v1/tasks/{identifier}/joined-results")
    def joined_results(identifier: str, actor: Actor):
        joined = service.joined_task_statuses(identifier, actor)
        if actor.role == "agent":
            return service.delegated_task_statuses(
                identifier, [item["task_id"] for item in joined["children"]], actor
            )
        return joined

    @app.post("/v1/experiments/{identifier}/submit-candidate", status_code=201)
    def submit_candidate_source(
        identifier: str, body: CandidateSourceInput, actor: Actor, key: Key
    ):
        return service.submit_candidate_source(identifier, body.source, actor, key)

    @app.get("/v1/branches/{identifier}/restart-brief")
    def restart_brief(identifier: str, actor: Actor):
        return service.restart_brief(identifier, actor)

    @app.post("/v1/sources", status_code=201)
    def ingest_source(body: SourceInput, actor: Actor, key: Key):
        return service.ingest_source(**body.model_dump(), actor=actor, key=key)

    @app.post("/v1/programs", status_code=201)
    def register_program(body: ProgramInput, actor: Actor, key: Key):
        return service.register_program(**body.model_dump(), actor=actor, key=key)

    @app.post("/v1/messages", status_code=201)
    def send_message(body: MessageInput, actor: Actor, key: Key):
        return service.send_message(**body.model_dump(), actor=actor, key=key)

    @app.get("/v1/branches/{identifier}/mailbox")
    def mailbox(identifier: str, actor: Actor, after: str | None = None):
        return service.mailbox_page(identifier, actor, after=after)

    @app.get("/v1/experiments/{identifier}/knowledge")
    def knowledge(
        identifier: str,
        actor: Actor,
        query: str = "",
        type_query: str = "",
        limit: int = Query(default=20, ge=1, le=100),
    ):
        return service.search_knowledge(identifier, query, actor, type_query, limit)

    @app.get("/v1/experiments/{identifier}/knowledge/{claim_id}/bundle")
    def knowledge_bundle(identifier: str, claim_id: str, actor: Actor):
        return service.knowledge_bundle(identifier, claim_id, actor)

    @app.post("/v1/branches/{identifier}/context", status_code=201)
    def context_checkpoint(identifier: str, body: ContextInput, actor: Actor, key: Key):
        from .memory import PortableMemory

        return PortableMemory(service).checkpoint(identifier, actor, key, **body.model_dump())

    @app.post("/v1/branches/{identifier}/research-notes", status_code=201)
    def research_notes(identifier: str, body: ResearchNotesInput, actor: Actor, key: Key):
        from .memory import PortableMemory

        return PortableMemory(service).checkpoint_research_notes(
            identifier, actor, key, **body.model_dump()
        )

    @app.get("/v1/branches/{identifier}/handoff-notes")
    def handoff_notes(identifier: str, actor: Actor, task_id: str | None = None):
        from .memory import PortableMemory

        return PortableMemory(service).handoff_notes(identifier, actor, task_id=task_id)

    @app.get("/v1/branches/{identifier}/context/{checkpoint_id}")
    def restore_context(identifier: str, checkpoint_id: str, actor: Actor):
        from .memory import PortableMemory

        return PortableMemory(service).restore(checkpoint_id, actor, expected_branch_id=identifier)

    @app.get("/v1/branches/{identifier}/history")
    def context_history(
        identifier: str,
        actor: Actor,
        kind: str,
        limit: int = Query(default=50, ge=1, le=100),
        after: str | None = None,
    ):
        from .memory import PortableMemory

        return PortableMemory(service).history_page(
            identifier, actor, kind=kind, limit=limit, after=after
        )

    @app.get("/v1/branches/{identifier}/working-context")
    def working_context(identifier: str, actor: Actor, task_id: str | None = None):
        from .memory import PortableMemory

        return PortableMemory(service).working_context(identifier, actor, task_id=task_id)

    @app.get("/v1/branches/{identifier}/index")
    def context_index(
        identifier: str,
        actor: Actor,
        index: str,
        limit: int = Query(default=50, ge=1, le=100),
        after: str | None = None,
    ):
        from .memory import PortableMemory

        return PortableMemory(service).index_page(
            identifier, actor, index=index, limit=limit, after=after
        )

    @app.get("/v1/branches/{identifier}/research-graph")
    def research_graph(
        identifier: str,
        actor: Actor,
        limit: int = Query(default=50, ge=1, le=100),
        after: str | None = None,
    ):
        from .memory import PortableMemory

        return PortableMemory(service).research_graph_page(
            identifier, actor, limit=limit, after=after
        )

    @app.get("/v1/branches/{identifier}/records/{kind}/{record_id}")
    def context_record(identifier: str, kind: str, record_id: str, actor: Actor):
        from .memory import PortableMemory

        return PortableMemory(service).read_record(
            identifier, actor, kind=kind, identifier=record_id
        )

    @app.get("/v1/branches/{identifier}/artifacts/{artifact_id}/chunk")
    def context_artifact_chunk(
        identifier: str, artifact_id: str, actor: Actor, offset: int = Query(default=0, ge=0)
    ):
        from .memory import PortableMemory

        return PortableMemory(service).read_artifact_chunk(
            identifier, actor, artifact_id=artifact_id, offset=offset
        )

    return app
