"""Bounded blueprint-commons inputs. Agents propose nodes and edges; never statuses."""

from typing import Annotated, Literal, get_args

from pydantic import Field, model_validator

from .domain import StrictModel

EdgeRelation = Literal[
    "depends_on", "motivated_by", "refutes", "generalizes", "specializes", "duplicates"
]
AuthoredNodeType = Literal[
    "lemma",
    "definition",
    "conjecture",
    "approach",
    "tangent",
    "obstacle",
    "counterexample",
    "computation",
]
# The goal node mirrors the reviewed target and is created only by the platform.
NODE_TYPES = ("goal", *get_args(AuthoredNodeType))
EDGE_RELATIONS = get_args(EdgeRelation)
STATUSES = (
    "informal",
    "refereed",
    "formally_stated",
    "compiles_locally",
    "accepted",
    "refuted",
    "abandoned",
)
CLOSED_STATUSES = frozenset({"accepted", "refuted", "abandoned"})
# Downward moves (to informal/refereed/formally_stated) happen only when a Lean
# statement changes. Only platform code applies any transition except author abandonment.
ALLOWED_TRANSITIONS = {
    "informal": {"refereed", "formally_stated", "refuted", "abandoned"},
    "refereed": {"informal", "formally_stated", "refuted", "abandoned"},
    "formally_stated": {
        "informal",
        "refereed",
        "compiles_locally",
        "accepted",
        "refuted",
        "abandoned",
    },
    "compiles_locally": {
        "informal",
        "refereed",
        "formally_stated",
        "accepted",
        "refuted",
        "abandoned",
    },
    "accepted": set(),
    "refuted": set(),
    "abandoned": set(),
}
LEAN_NAME = r"^[A-Za-z_][A-Za-z0-9_.']{0,199}$"
# A local compile counts only on Lean's standard axioms; anything else (sorryAx, an added
# axiom, Lean.ofReduceBool, a native_decide axiom) leaves the node where it is.
STANDARD_AXIOMS = frozenset({"propext", "Classical.choice", "Quot.sound"})
MAX_AXIOM_REPORT = 32


def axiom_refusal(axioms, lean_name):
    """Why an axiom report cannot support compiles_locally, or None when it can.

    Only the node's own theorem entry counts: a missing or malformed entry fails closed, and
    other declarations' entries never stand in for it.
    """
    entry = axioms.get(lean_name) if isinstance(axioms, dict) else None
    if not isinstance(entry, list) or not all(isinstance(name, str) for name in entry):
        return {"recorded": False, "reason": "axioms_unreported"}
    nonstandard = sorted(set(entry) - STANDARD_AXIOMS)
    if nonstandard:
        return {
            "recorded": False,
            "reason": "nonstandard_axioms",
            "axioms": nonstandard[:MAX_AXIOM_REPORT],
        }
    return None


class EdgeSpec(StrictModel):
    relation: EdgeRelation
    target_id: str = Field(min_length=1, max_length=36)


class NodeCreate(StrictModel):
    node_type: AuthoredNodeType
    title: str = Field(min_length=1, max_length=200)
    statement: str = Field(min_length=1, max_length=8000)
    assumptions: list[Annotated[str, Field(min_length=1, max_length=512)]] = Field(
        default_factory=list, max_length=32
    )
    # Import/open lines; `theorem <lean_name> <lean_statement>` must be valid Lean.
    lean_header: str | None = Field(default=None, max_length=2000)
    lean_statement: str | None = Field(default=None, min_length=1, max_length=20000)
    lean_name: str | None = Field(default=None, pattern=LEAN_NAME)
    edges: list[EdgeSpec] = Field(default_factory=list, max_length=16)
    artifact_ids: list[Annotated[str, Field(min_length=1, max_length=36)]] = Field(
        default_factory=list, max_length=12
    )

    @model_validator(mode="after")
    def coherent_node(self):
        if not self.title.strip() or not self.statement.strip():
            raise ValueError("A node needs a substantive title and informal statement")
        if (self.lean_name is None) != (self.lean_statement is None):
            raise ValueError("Supply both lean_name and lean_statement, or neither")
        if self.lean_header is not None and self.lean_statement is None:
            raise ValueError("A Lean header requires a Lean statement")
        if len({(e.relation, e.target_id) for e in self.edges}) != len(self.edges):
            raise ValueError("Edges must be unique")
        if len(set(self.artifact_ids)) != len(self.artifact_ids):
            raise ValueError("Artifact references must be unique")
        if self.node_type == "tangent" and not any(
            e.relation == "motivated_by" for e in self.edges
        ):
            raise ValueError(
                "TANGENT_MOTIVATION_REQUIRED: a tangent needs a motivated_by edge to its origin"
            )
        return self


class NodePostCreate(StrictModel):
    kind: Literal["question", "finding", "objection", "attempt_failed", "synthesis", "update"]
    # Structured header (claim / evidence status / ask) delivered in digests.
    abstract: str = Field(min_length=1, max_length=600)
    # Retrieved on demand with the exact post.
    body: str = Field(default="", max_length=12000)
    cites: list[Annotated[str, Field(min_length=1, max_length=36)]] = Field(
        default_factory=list, max_length=20
    )
    artifact_ids: list[Annotated[str, Field(min_length=1, max_length=36)]] = Field(
        default_factory=list, max_length=12
    )
    reply_to_post_id: str | None = Field(default=None, min_length=1, max_length=36)

    @model_validator(mode="after")
    def coherent_post(self):
        if not self.abstract.strip():
            raise ValueError("A post needs a substantive abstract")
        if len(set(self.cites)) != len(self.cites):
            raise ValueError("Cited nodes must be unique")
        if len(set(self.artifact_ids)) != len(self.artifact_ids):
            raise ValueError("Artifact references must be unique")
        return self
