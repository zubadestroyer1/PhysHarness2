"""The lemma store: each commons node's Lean module and its ranked published source.

A node's Lean module is ``Commons.N<hex>`` (8 hex of its id, lengthened on a collision). A
clean ``lean_check`` against the node publishes the checked file as the node's source,
ranked ``verified`` (the statement check passed on standard axioms), ``complete`` (no
``sorry``, but the check could not judge) or ``partial``. A higher rank replaces a lower
one; a verified source of the node's current statement is replaced only by its publisher or
the node's author (S1 audit #12).

A file imports node modules with ``import Commons.N…``. The platform inlines them: each
module's published source, or a ``sorry`` stub of an elaborated statement, goes into one
self-contained file (``inline_commons``) that ``lean_check`` checks and the verifier gets.
"""

import re
from dataclasses import dataclass

from .commons_models import CLOSED_STATUSES
from .domain import utcnow
from .errors import HarnessError
from .orchestration.lean_session import lean_code
from .worker_authority import current_worker_effects

RANKS = {"partial": 1, "complete": 2, "verified": 3}
COMPLETE_RANKS = frozenset({"complete", "verified"})
SOURCE_STATES = ("verified", "complete", "partial", "stub", "none")
MODULE = re.compile(r"Commons\.N([0-9a-f]{8}|[0-9a-f]{12}|[0-9a-f]{16})")
SKIPPED_IMPORT_EDGES = frozenset({"DEPENDENCY_CYCLE", "SELF_EDGE"})
COMMONS_IMPORT = re.compile(r"Commons\.N[0-9a-f]{8}(?:[0-9a-f]{4}){0,2}")
MAX_COMMONS_MODULES = 200
_SCOPE = re.compile(r"(?<![\w.'!?])(namespace|section|mutual|end)(?![\w'!?])")
_SCOPE_NAME = re.compile(r"[ \t]+([\w.'!?]+)")


@dataclass(frozen=True)
class Module:
    """One resolved node module. ``stale``: its source was checked against an older
    statement than the node's current one, so it is no proof of that statement."""

    name: str
    node_id: str
    source: str
    rank: str
    sha256: str | None = None
    artifact_id: str | None = None
    branch_id: str | None = None
    stale: bool = False


@dataclass(frozen=True)
class Expansion:
    """A flattened file. ``segments`` are ``(first_line, last_line, module_or_None,
    origin_line)`` in its 1-based lines; None marks the caller's own lines."""

    source: str
    modules: tuple = ()
    segments: tuple = ()
    closure_complete: bool = True
    stubs: tuple = ()


def node_module(node: dict) -> str:
    """The node's module name; nodes recorded before modules existed use 8 hex of the id."""
    return node.get("lean_module") or "Commons.N" + node["id"][:8]


def module_prefix(module: str) -> str | None:
    """The dashed record-id prefix a module name encodes, or None for another name."""
    match = MODULE.fullmatch(module) if isinstance(module, str) else None
    if match is None:
        return None
    hexid = match.group(1)
    return hexid[:8] + "".join("-" + hexid[i : i + 4] for i in range(8, len(hexid), 4))


def _statement_digest(node):
    from .commons import _lean_digest  # commons imports this module for its node views

    return _lean_digest(node.get("lean_header"), node.get("lean_name"), node.get("lean_statement"))


def _effective_rank(source, digest):
    """A verified source of an older statement counts as complete."""
    if source["rank"] == "verified" and source.get("lean_statement_sha256") != digest:
        return "complete"
    return source["rank"]


def node_refusal(node: dict) -> str | None:
    """Why a node takes no published source (the goal, or a closed node), or None."""
    if node["node_type"] == "goal":
        return "goal_node"
    if node["status"] in CLOSED_STATUSES:
        return "node_closed"
    return None


def blocking_rank(node: dict, rank: str, branch_id: str | None) -> str | None:
    """The effective rank of the node's source when it keeps its place against a new source
    of ``rank`` from ``branch_id``, else None. At equal rank the newer source wins, except
    that a verified source of the current statement answers only to its publisher and the
    node's author."""
    current = node.get("lean_source")
    if current is None:
        return None
    held = _effective_rank(current, _statement_digest(node))
    if RANKS[rank] < RANKS[held] or (
        rank == held == "verified"
        and branch_id not in (current.get("branch_id"), node.get("branch_id"))
    ):
        return held
    return None


def source_state(node: dict) -> str:
    """The node's effective source rank; ``stub`` for an elaborated Lean statement with no
    source (it imports as a ``sorry`` stub), else ``none``."""
    source = node.get("lean_source")
    if source:
        return _effective_rank(source, _statement_digest(node))
    if node.get("lean_statement") is not None and node.get("lean_elaborated"):
        return "stub"
    return "none"


def split_imports(source):
    """(commons modules, environment import lines, the lines from the first non-import
    line on, that line's 0-based index). Blank lines and comments before it are skipped."""
    lines, modules, env = source.split("\n"), [], []
    # Blanked comments keep their newlines, so code lines match source lines up to the
    # first non-import line. A source too nested to scan is read as written.
    for index, line in enumerate((lean_code(source) or source).split("\n")):
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


def scope_closers(module, source):
    """`end` lines for the scopes a module leaves open; refuses an `end` it never opened."""
    code, stack = lean_code(source), []
    for match in _SCOPE.finditer(code):
        label = _SCOPE_NAME.match(code, match.end())
        if match.group(1) == "end":
            if not stack:
                raise HarnessError(
                    "COMMONS_MODULE_REFUSED",
                    f"{module} closes a scope it never opened.",
                    status=422,
                    details={"module": module},
                )
            stack.pop()
        else:
            stack.append(label.group(1) if label and match.group(1) != "mutual" else "")
    return [f"end {label}".rstrip() for label in reversed(stack)]


def _too_large(size, limit):
    return HarnessError(
        "COMMONS_EXPANSION_TOO_LARGE",
        f"The flattened file would be at least {size:,} bytes; the limit here is {limit:,}.",
        status=422,
        details={"bytes": size, "limit": limit},
        remediation="Write it with commons_fetch(expand_path=…) and check it with lake env "
        "lean in the shell.",
    )


def inline_commons(source, resolve, *, max_bytes):
    """Flatten `import Commons.N…` into one self-contained file (S1 audit #12): environment
    imports hoisted once, each module in dependency order inside its own section, then the
    caller's lines. A source without commons imports is returned unchanged.

    ``resolve(name)`` returns a ``Module``. Every module's own lines appear in the output,
    so their running total stops an oversized closure before the rest is resolved.
    """
    imports = split_imports(source)
    if not imports[0]:
        return Expansion(source)
    ordered, active, done = [], [], set()
    floor = len("\n".join(imports[2]).encode("utf-8"))

    def visit(name):
        nonlocal floor
        if name in done:
            return
        if name in active:
            raise HarnessError(
                "COMMONS_IMPORT_CYCLE",
                f"{name} imports itself through {', '.join(active)}.",
                status=422,
                details={"modules": [*active, name]},
            )
        if len(done) + len(active) >= MAX_COMMONS_MODULES:
            raise HarnessError(
                "COMMONS_EXPANSION_LIMIT",
                f"A closure inlines at most {MAX_COMMONS_MODULES} modules.",
                status=422,
            )
        active.append(name)
        found = resolve(name)
        if "#exit" in found.source:
            raise HarnessError(
                "COMMONS_MODULE_REFUSED",
                f"{name} contains #exit.",
                status=422,
                details={"module": name},
            )
        parts = split_imports(found.source)
        closers = scope_closers(name, found.source)
        floor += len("\n".join(parts[2]).encode("utf-8"))
        if floor > max_bytes:
            raise _too_large(floor, max_bytes)
        for child in parts[0]:
            visit(child)
        active.pop()
        done.add(name)
        ordered.append((found, parts, closers))

    for name in imports[0]:
        visit(name)
    out = []
    for env in (imports[1], *(parts[1] for _, parts, _ in ordered)):
        out += [line for line in env if line not in out]
    segments = []
    for found, parts, closers in ordered:
        label = f"-- {found.name}: node {found.node_id}, {found.rank}"
        block = ["section", label + (", stale" if found.stale else ""), *parts[2], *closers]
        block.append("end")
        segments.append((len(out) + 1, len(out) + len(block), found.name, 1))
        out += block
    _, _, rest, first = imports
    segments.append((len(out) + 1, len(out) + len(rest), None, first + 1))
    flat = "\n".join(out + rest)
    size = len(flat.encode("utf-8"))
    if size > max_bytes:
        raise _too_large(size, max_bytes)
    modules = tuple(found for found, _, _ in ordered)
    return Expansion(
        flat,
        modules,
        tuple(segments),
        all(m.rank in COMPLETE_RANKS for m in modules),
        tuple(m.node_id for m in modules if m.rank == "stub"),
    )


def remap(result, expansion):
    """A check of a flattened file, reported on the caller's own lines. A line inside an
    inlined module names the module and its line in the flattened file instead."""
    if not expansion.modules:
        return result

    def moved(item):
        line = item.get("line")
        if line is None:
            return item
        for first, last, module, origin in expansion.segments:
            if first <= line <= last:
                if module is None:
                    return {**item, "line": origin + line - first}
                return {**item, "line": None, "module": module, "expanded_line": line}
        return {**item, "line": None, "expanded_line": line}  # a hoisted import, say

    return {
        **result,
        "messages": [moved(item) for item in result["messages"]],
        "holes": [moved(item) for item in result["holes"]],
    }


class CommonsSourceMixin:
    def _module_node(self, session, module, actor, experiment_id):
        """The experiment's node whose module is ``module``."""
        prefix = module_prefix(module)
        if prefix is not None:
            for row in self._prefix_candidates(session, prefix, actor, ("commons_node",)):
                if (
                    row.payload.get("experiment_id") == experiment_id
                    and node_module(row.payload) == module
                ):
                    return row
        raise HarnessError(
            "COMMONS_MODULE_NOT_FOUND",
            f"No commons node has the module {str(module)[:100]}.",
            status=404,
            details={"module": module},
            remediation="Import a module name a node reports (commons_read, commons_query).",
        )

    def _module(self, session, name, actor, experiment_id) -> Module:
        """The module as inlined: the node's live published source at its effective rank,
        else a ``sorry`` stub of its elaborated Lean statement."""
        row = self._module_node(session, name, actor, experiment_id)
        node, source = row.payload, row.payload.get("lean_source")
        digest = _statement_digest(node)
        if source is not None:
            return Module(
                name,
                row.id,
                self.artifacts.get(source["sha256"]).decode("utf-8"),
                _effective_rank(source, digest),
                source["sha256"],
                source["artifact_id"],
                source["branch_id"],
                stale=source.get("lean_statement_sha256") != digest,
            )
        if node.get("lean_statement") is not None and node.get("lean_elaborated"):
            header, statement = node.get("lean_header") or "", node["lean_statement"]
            stub = f"{header}\n\ntheorem {node['lean_name']} {statement} := sorry\n"
            return Module(name, row.id, stub, "stub")
        raise HarnessError(
            "COMMONS_MODULE_NOT_FOUND",
            f"{name} has no published source and no elaborated Lean statement.",
            status=404,
            details={"module": name},
            remediation="Publish a source with lean_check(node_id=…), or give the node an "
            "elaborated Lean statement to import it as a sorry stub.",
        )

    def expand_commons(self, experiment_id, source, actor, *, max_bytes) -> Expansion:
        """``source`` with its ``import Commons.N…`` inlined from the experiment's live node
        modules; a source that names no module is returned unchanged, without a read."""
        if not COMMONS_IMPORT.search(source):
            return Expansion(source)
        with self.db.sessions() as session:
            return inline_commons(
                source,
                lambda name: self._module(session, name, actor, experiment_id),
                max_bytes=max_bytes,
            )

    def record_lean_source(self, node_id, artifact_id, record, actor, key) -> dict:
        """Publish a checked ``lean_source`` artifact as the node's source, by the rank rule.

        ``record`` is platform evidence assembled by ``lean_check``: ``rank``, ``bytes``,
        ``statement_check``, ``lean_statement_sha256`` (the statement the file was checked
        against) and ``imports`` (``[{module, node_id, sha256}]``, each a depends_on edge).
        """
        self._research_role(actor)
        if not isinstance(record, dict) or record.get("rank") not in RANKS:
            raise HarnessError(
                "INVALID_SOURCE_RECORD", f"A source rank is one of: {', '.join(RANKS)}.", status=422
            )
        inputs = {"node_id": node_id, "artifact_id": artifact_id, "record": record}

        def action(session, op):
            row, experiment = self._review_node(session, node_id, actor)
            node = row.payload
            module = node_module(node)
            refusal = node_refusal(node)
            if refusal is not None:
                return {"recorded": False, "module": module, "reason": refusal}
            artifact = self._get(session, "artifact", artifact_id, actor)
            if (
                artifact.payload.get("artifact_kind") != "lean_source"
                or artifact.payload.get("experiment_id") != experiment.id
                or artifact.payload.get("branch_id") != actor.branch_id
            ):
                raise HarnessError(
                    "SOURCE_ARTIFACT_SCOPE",
                    "A published source is a lean_source artifact of the publisher's branch in "
                    "the node's experiment.",
                    status=403,
                )
            digest = _statement_digest(node)
            if digest is not None and record["lean_statement_sha256"] != digest:
                return {"recorded": False, "module": module, "reason": "statement_changed"}
            rank, current = record["rank"], node.get("lean_source")
            held = blocking_rank(node, rank, actor.branch_id)
            if held is not None:
                return {"recorded": False, "module": module, "reason": "lower_rank", "rank": held}
            binding = current_worker_effects.get()
            source = {
                "artifact_id": artifact.id,
                "sha256": artifact.payload["sha256"],
                "bytes": record["bytes"],
                "branch_id": actor.branch_id,
                "task_id": binding.task_id if binding is not None else None,
                "rank": rank,
                "statement_check": record["statement_check"],
                "lean_statement_sha256": record["lean_statement_sha256"],
                "imports": record["imports"],
                "recorded_at": utcnow().isoformat(),
            }
            self._replace(session, row, {"lean_source": source})
            for entry in record["imports"]:
                try:
                    self._add_edge(
                        session, op, experiment, row.id, "depends_on", entry["node_id"], actor
                    )
                except HarnessError as error:
                    if error.code not in SKIPPED_IMPORT_EDGES:
                        raise
            self._touch_node(session, row, actor, op)
            replaced = current is not None
            self._event(
                session,
                actor,
                op,
                "commons.source_published",
                row.id,
                {
                    "experiment_id": experiment.id,
                    "node_id": row.id,
                    "branch_id": actor.branch_id,
                    "artifact_id": artifact.id,
                    "sha256": source["sha256"],
                    "rank": rank,
                    "replaced": replaced,
                },
            )
            return {"recorded": True, "module": module, "rank": rank, "replaced": replaced}

        return self._execute(actor, key, "commons.source_publish", inputs, action)
