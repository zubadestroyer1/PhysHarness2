"""The lemma store: each commons node's Lean module and its ranked published source.

A node's Lean module is ``Commons.N<hex>`` (8 hex of its id, lengthened on a collision). A
clean ``lean_check`` against the node publishes the checked file as the node's source,
ranked ``verified`` (the statement check passed on standard axioms), ``complete`` (no
``sorry``, but the check could not judge) or ``partial``. A higher rank replaces a lower
one; a verified source of the node's current statement is replaced only by its publisher or
the node's author (S1 audit #12). A node's first complete source of an elaborated Lean
statement tells its other claimants to consider stopping their routes (S1 audit #22).

A file imports node modules with ``import Commons.N…``. The platform inlines them: each
module's published source, or a ``sorry`` stub of an elaborated statement, goes into one
self-contained file (``inline_commons``) that ``lean_check`` checks and the verifier gets.
"""

import re
from collections import deque
from dataclasses import dataclass

from .commons_models import axiom_refusal, is_open
from .domain import utcnow
from .errors import HarnessError
from .orchestration.lean_session import _ID_FIRST, _command_word, lean_code
from .storage import RecordRow
from .worker_authority import current_worker_effects

RANKS = {"partial": 1, "complete": 2, "verified": 3}
COMPLETE_RANKS = frozenset({"complete", "verified"})
SOURCE_STATES = ("verified", "complete", "partial", "stale", "stub", "none")
MODULE = re.compile(r"Commons\.N([0-9a-f]{8}|[0-9a-f]{12}|[0-9a-f]{16})")
SKIPPED_IMPORT_EDGES = frozenset({"DEPENDENCY_CYCLE", "SELF_EDGE"})
COMMONS_IMPORT = re.compile(r"Commons\.N[0-9a-f]{8}(?:[0-9a-f]{4}){0,2}")
MAX_COMMONS_MODULES = 200
_MODULE_NAME = re.compile(r"[A-Za-z_][\w.']*")
# Lean's identifier characters, not Python's \w: after notation such as `ᵀ`, Lean reads `end`.
_ID_REST = _ID_FIRST + "0-9'\u2080-\u2089\u2090-\u209c\u1d62-\u1d6a"
_SCOPE = re.compile(rf"(?<![{_ID_REST}.!?])(namespace|section|mutual|end)(?![{_ID_REST}!?])")
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


def _stale(source, digest):
    """Whether a source was checked against another statement than the node's current one
    (``digest``): it proves nothing of the current statement."""
    return source.get("lean_statement_sha256") != digest


def _effective_rank(source, digest):
    """The rank a source holds for import: a verified source of an older statement counts
    as complete (the importer inlines it, flagged stale)."""
    if source["rank"] == "verified" and _stale(source, digest):
        return "complete"
    return source["rank"]


def _complete_for(source, digest):
    """Whether ``source`` is complete for the statement ``digest``; a source of an older
    statement is stale and counts as none."""
    return source is not None and not _stale(source, digest) and source["rank"] in COMPLETE_RANKS


def _verified_evidence(node, check):
    """Whether a statement-check record supports the verified rank: the check passed, and
    it found only Lean's standard axioms for the node's theorem."""
    name = node.get("lean_name")
    return (
        isinstance(check, dict)
        and check.get("ok") is True
        and axiom_refusal({name: check.get("axioms")}, name) is None
    )


def node_refusal(node: dict) -> str | None:
    """Why a node takes no published source (the goal, or a closed node), or None."""
    if node["node_type"] == "goal":
        return "goal_node"
    if not is_open(node["status"]):
        return "node_closed"
    return None


def blocking_rank(node: dict, rank: str, branch_id: str | None) -> str | None:
    """The rank of the node's source when it keeps its place against a new source of
    ``rank`` from ``branch_id``, else None. A stale source counts as no source: any source
    of the current statement replaces it. At equal rank the newer source wins, except that
    a verified source answers only to its publisher and the node's author."""
    current = node.get("lean_source")
    if current is None or _stale(current, _statement_digest(node)):
        return None
    held = current["rank"]
    if RANKS[rank] < RANKS[held] or (
        rank == held == "verified"
        and branch_id not in (current.get("branch_id"), node.get("branch_id"))
    ):
        return held
    return None


def has_elaborated_statement(node: dict) -> bool:
    """Whether the node has an elaborated Lean statement: only then does a clean file prove
    something the verifier could check."""
    return node.get("lean_statement") is not None and bool(node.get("lean_elaborated"))


def source_state(node: dict) -> str:
    """What the node's source proves of its current statement: its rank, or ``stale`` when
    it was checked against another statement (so it is never complete); ``stub`` for an
    elaborated Lean statement with no source (it imports as a ``sorry`` stub), else
    ``none``."""
    source = node.get("lean_source")
    if source:
        return "stale" if _stale(source, _statement_digest(node)) else source["rank"]
    if has_elaborated_statement(node):
        return "stub"
    return "none"


def _module_name(token):
    return _MODULE_NAME.fullmatch(token) is not None and not _command_word(token)


def split_imports(source):
    """(commons modules, environment import lines, the lines after the imports, the first
    such line's 0-based index). An import line holds only module names; any other line, a
    comment or blank line aside, ends the imports and stays where it is."""
    lines, modules, env, end = source.split("\n"), [], [], 0
    # Blanked comments keep their newlines, so code lines match source lines up to the
    # first non-import line. A source too nested to scan is read as written.
    for index, line in enumerate((lean_code(source) or source).split("\n")):
        words = line.split("--", 1)[0].split()
        if not words:
            continue
        names = words[1:]
        if words[0] != "import" or not names or not all(map(_module_name, names)):
            return modules, env, lines[index:], index
        modules += [n for n in names if COMMONS_IMPORT.fullmatch(n) and n not in modules]
        others = [n for n in names if not COMMONS_IMPORT.fullmatch(n)]
        if others:
            env.append("import " + " ".join(others))
        end = index + 1
    return modules, env, lines[end:], end


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
                    remediation=_REPUBLISH,
                )
            stack.pop()
        else:
            stack.append(label.group(1) if label and match.group(1) != "mutual" else "")
    return [f"end {label}".rstrip() for label in reversed(stack)]


_REPUBLISH = (
    "Republish the module without #exit and with every end matching a namespace or section "
    "it opened, or do not import it."
)


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
                remediation="Republish one module of the cycle without the import that closes "
                "it; a source that imports its own module is no longer published.",
            )
        if len(done) + len(active) >= MAX_COMMONS_MODULES:
            raise HarnessError(
                "COMMONS_EXPANSION_LIMIT",
                f"A closure inlines at most {MAX_COMMONS_MODULES} modules.",
                status=422,
                remediation="Import fewer modules, or copy the few lemmas you need into the file.",
            )
        active.append(name)
        found = resolve(name)
        if "#exit" in found.source:
            raise HarnessError(
                "COMMONS_MODULE_REFUSED",
                f"{name} contains #exit.",
                status=422,
                details={"module": name},
                remediation=_REPUBLISH,
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


def _imports_reach(session, node_id, imports):
    """Whether ``node_id`` is reachable from ``imports`` along the stored sources' imports.

    Each row is read afresh, never a copy the session cached before the caller's lock, and
    at most ``MAX_COMMONS_MODULES`` are read: a larger closure cannot be inlined anyway.
    """
    queue, seen = deque(entry["node_id"] for entry in imports), set()
    while queue:
        current = queue.popleft()
        if current == node_id:
            return True
        if current in seen or len(seen) >= MAX_COMMONS_MODULES:
            continue
        seen.add(current)
        row = session.get(RecordRow, current, populate_existing=True)
        source = (row.payload.get("lean_source") if row is not None else None) or {}
        queue.extend(entry["node_id"] for entry in source.get("imports", ()))
    return False


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
                stale=_stale(source, digest),
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

    def commons_module(self, node_id, actor) -> dict:
        """A node's module as an importer inlines it, for ``commons_fetch``."""
        self._research_role(actor)
        with self.db.sessions() as session:
            row = self._get(session, "commons_node", node_id, actor)
            if row.payload["node_type"] == "goal":
                raise HarnessError(
                    "COMMONS_MODULE_NOT_FOUND",
                    "The goal node has no module: nothing imports the target.",
                    status=404,
                    details={"node_id": row.id},
                    remediation="Fetch the modules of the nodes the goal depends on.",
                )
            found = self._module(
                session, node_module(row.payload), actor, row.payload["experiment_id"]
            )
        return {
            "node_id": found.node_id,
            "module": found.name,
            "source": found.source,
            "rank": found.rank,
            "sha256": found.sha256,
        }

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
        A source whose imports reach the node through the stored sources' imports is refused
        (``imports_own_module``): published, the module would import itself.
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
            if record["rank"] == "verified" and not _verified_evidence(
                node, record.get("statement_check")
            ):
                # The rank exempts a node from review and locks its statement (S1 audit #17).
                raise HarnessError(
                    "INVALID_SOURCE_RECORD",
                    "A verified rank needs a passing statement check on Lean's standard axioms.",
                    status=422,
                )
            rank, current = record["rank"], node.get("lean_source")
            held = blocking_rank(node, rank, actor.branch_id)
            if held is not None:
                return {"recorded": False, "module": module, "reason": "lower_rank", "rank": held}
            if _imports_reach(session, row.id, record["imports"]):
                # lean_check refuses this before the check; under the experiment lock the
                # stored graph also covers a concurrent publication it could not see.
                return {"recorded": False, "module": module, "reason": "imports_own_module"}
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
            if (
                rank in COMPLETE_RANKS
                and has_elaborated_statement(node)
                and not _complete_for(current, digest)
            ):
                # First reach only: a re-publication at a complete rank never re-posts.
                route = next(
                    (
                        claim["route"]
                        for claim in self._active_claims(session, row.id)
                        if claim["branch_id"] == actor.branch_id
                    ),
                    None,
                )
                self._post_route_compiled(session, row, actor.branch_id, route, op)
            replaced = current is not None
            # A source of an older statement is stale: the new one is a first publication.
            fresh = replaced and not _stale(current, digest)
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
                    "previous_rank": current["rank"] if fresh else None,
                },
            )
            return {"recorded": True, "module": module, "rank": rank, "replaced": replaced}

        return self._execute(actor, key, "commons.source_publish", inputs, action)
