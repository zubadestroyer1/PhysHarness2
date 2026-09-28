"""The lemma store: each commons node's Lean module and its ranked published source.

A node's Lean module is ``Commons.N<hex>`` (8 hex of its id, lengthened on a collision). A
clean ``lean_check`` against the node publishes the checked file as the node's source,
ranked ``verified`` (the statement check passed on standard axioms), ``complete`` (no
``sorry`` on standard axioms, for a node with no Lean statement to check) or ``partial``
(also when the statement check could not judge). A higher rank replaces a lower
one; a complete or verified source of the node's current statement is replaced at its rank
only by its publisher or the node's author (S1 audit #12). A node's first complete source
of an elaborated Lean statement tells its other claimants to consider stopping their routes
(S1 audit #22).

A file imports node modules with ``import Commons.N…``. The platform inlines them: each
module's published source, or a ``sorry`` stub of an elaborated statement, goes into one
self-contained file (``inline_commons``) that ``lean_check`` checks and the verifier gets.
A published module holds no code that would run in an importer's VM (``refused_command``),
and a source proves its node only while each module its check inlined is still its node's
source (``Closures``).
"""

import copy
import re
from collections import deque
from dataclasses import dataclass

from .commons_models import axiom_refusal, is_open
from .domain import utcnow
from .errors import HarnessError
from .orchestration.lean_session import (
    _ID_FIRST,
    HEADER_OPTION_PREFIXES,
    HEADER_OPTIONS,
    _command_word,
    lean_code,
)
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
# What a published module may not hold. Importers inline it, and so may a referee's
# lean_check: its compile-time code would run in their VMs, where it can read and overwrite
# their files, and a global syntax extension would change how their own lines read (a
# `sorry` that is none, a redefined `#print axioms`). Commands and modifiers that run code or
# extend syntax, and the prefixes of Lean's and Mathlib's registration commands
# (`register_option`, `declare_aesop_rule_sets`, `builtin_initialize`, …):
_RUNS_CODE = frozenset(
    "run_cmd run_elab run_meta run_tac by_elab elab elab_rules macro macro_rules syntax "
    "declare_syntax_cat binder_predicate initialize builtin_initialize simproc dsimproc "
    "simproc_decl dsimproc_decl unsafe".split()
)
_REGISTERS = ("builtin_", "declare_", "register_")
# Notation only as `local`, which ends with the section the inliner wraps the module in.
_NOTATION = frozenset("notation notation3 infix infixl infixr prefix postfix".split())
# Attributes (`@[…]`, `attribute […]`) that hand the elaborator code to run.
_CODE_ATTRIBUTES = frozenset(
    "command_elab term_elab tactic macro init builtin_init implemented_by extern env_linter "
    "delab app_unexpander norm_num positivity simproc dsimproc widget_module".split()
)
_CODE_ATTRIBUTE_SUFFIXES = (
    "_elab",
    "_parser",
    "_delab",
    "_unexpander",
    "_code_action",
    "_formatter",
    "_parenthesizer",
)
# The `#` commands that only report; `#eval` and the others run code or write files.
_REPORTS = frozenset(("#check", "#check_failure", "#print", "#reduce", "#synth"))
# A metaprogram or IO action is written with these namespaces' names, so a module that names
# none defines no code for a tactic's configuration or an `evalConst` to run.
_META_NAMESPACES = frozenset(("Lean", "IO", "EIO", "BaseIO"))
_WORD = rf"[{_ID_FIRST}][{_ID_REST}!?]*"
_TOKEN = re.compile(rf"#{_WORD}|@\[|(?<![{_ID_REST}.!?]){_WORD}(?:\.{_WORD})*")
_OPTION = re.compile(rf"\s+({_WORD}(?:\.{_WORD})*)")
_BRACKET = re.compile(r"\s*\[")
_LOCAL = re.compile(rf"(?<![{_ID_REST}.!?])local\s+$")
_ESCAPED_META = re.compile("«(?:" + "|".join(sorted(_META_NAMESPACES)) + ")»")


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


def blocking_rank(node: dict, rank: str, branch_id: str | None, state: str) -> str | None:
    """The rank of the node's source when it keeps its place against a new source of
    ``rank`` from ``branch_id``, else None. ``state`` is the node's ``source_state``: a
    stale source (of another statement, or whose imports changed since) counts as no
    source, so any source of the current statement replaces it. At equal rank the newer
    source wins, except that a complete or verified source answers only to its publisher
    and the node's author: other nodes' sources may import it, and each goes stale when it
    is replaced, so another branch cannot churn equal-rank sources under them."""
    if state not in RANKS:
        return None
    current = node["lean_source"]
    held = current["rank"]
    if RANKS[rank] < RANKS[held] or (
        rank == held
        and held in COMPLETE_RANKS
        and branch_id not in (current.get("branch_id"), node.get("branch_id"))
    ):
        return held
    return None


def has_elaborated_statement(node: dict) -> bool:
    """Whether the node has an elaborated Lean statement: only then does a clean file prove
    something the verifier could check."""
    return node.get("lean_statement") is not None and bool(node.get("lean_elaborated"))


def statement_state(node: dict) -> str:
    """What the node's source proves of its current statement, judged by the statement
    alone: its rank, or ``stale`` when it was checked against another statement; ``stub``
    for an elaborated Lean statement with no source (it imports as a ``sorry`` stub), else
    ``none``. ``source_state`` also judges what the source imported."""
    source = node.get("lean_source")
    if source:
        return "stale" if _stale(source, _statement_digest(node)) else source["rank"]
    if has_elaborated_statement(node):
        return "stub"
    return "none"


class Closures:
    """Whether a node's published source still stands on the Lean its check inlined (PR 37
    review): every module that check inlined (``closure``, recorded at publication) is
    still its node's source, by digest. A source recorded without ``closure`` stands while
    each direct import is its node's source and that source stands too. A changed
    statement of an imported node changes no Lean the importer checked, so it stales only
    that node's own source.

    ``lookup(node_id)`` returns a node payload or None. Each node is judged once, so one
    instance serves a whole graph; build one per call.
    """

    def __init__(self, lookup):
        self._lookup, self._stands = lookup, {}

    @classmethod
    def over(cls, nodes):
        """Judged over these node payloads, which hold every node an import names."""
        return cls({node["id"]: node for node in nodes}.get)

    @classmethod
    def reading(cls, session, experiment_id):
        """Judged over the experiment's node rows, read through ``session``."""

        def lookup(node_id):
            row = session.get(RecordRow, node_id)
            if (
                row is None
                or row.kind != "commons_node"
                or row.payload.get("experiment_id") != experiment_id
            ):
                return None
            return row.payload

        return cls(lookup)

    def _child(self, entry):
        """The node an import entry names, while its source is still the one recorded."""
        child = self._lookup(entry["node_id"])
        current = (child or {}).get("lean_source") or {}
        return child if child is not None and current.get("sha256") == entry["sha256"] else None

    def stands(self, node, depth=0):
        if node["id"] in self._stands:
            return self._stands[node["id"]]
        self._stands[node["id"]] = False  # a cycle, or a chain too long to inline, fails
        source = node.get("lean_source") or {}
        recorded = source.get("closure")
        entries = (source.get("imports") or ()) if recorded is None else recorded
        children = map(self._child, entries)
        stands = depth < MAX_COMMONS_MODULES and all(
            child is not None and (recorded is not None or self.stands(child, depth + 1))
            for child in children
        )
        self._stands[node["id"]] = stands
        return stands


def source_state(node: dict, closures: Closures) -> str:
    """What the node's source proves of its current statement: its rank; ``stale`` when it
    was checked against another statement, or when a module its check inlined is no longer
    its node's source (``closures``), so it is never complete; ``stub`` for an elaborated
    Lean statement with no source (it imports as a ``sorry`` stub), else ``none``."""
    state = statement_state(node)
    if state in RANKS and not closures.stands(node):
        return "stale"
    return state


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


def _bracketed(code, start):
    """The text from ``start`` to its unmatched ``]``, or None when there is none."""
    depth = 0
    for index in range(start, len(code)):
        if code[index] == "[":
            depth += 1
        elif code[index] == "]":
            if not depth:
                return code[start:index]
            depth -= 1
    return None


def refused_command(source):
    """The first command, attribute, option or name in ``source`` after its imports that no
    published module may hold, or None (PR 37 review): a command or modifier that runs code
    or extends syntax (``_RUNS_CODE``, ``_REGISTERS``), notation that is not ``local``, a
    ``#`` command other than ``_REPORTS``, a code attribute, a ``set_option`` of an option a
    node header may not set, or a name in ``_META_NAMESPACES``.

    It reads ``lean_code``, so comments and literals count for nothing; a source too nested
    to scan is refused. ``#v[`` (a vector literal) is no command; Mathlib's ``#s`` for a
    finset's card is refused with the commands (write ``#(s)`` or ``s.card``).
    """
    body = "\n".join(split_imports(source)[2])
    code = lean_code(body)
    if body.strip() and not code:
        return "(a source too nested to scan)"
    for match in _TOKEN.finditer(code):
        word, end = match.group(), match.end()
        if word.startswith("#"):
            if word not in _REPORTS and not (word == "#v" and code.startswith("[", end)):
                return word
        elif word in ("@[", "attribute"):
            bracket = _BRACKET.match(code, end) if word == "attribute" else None
            if word == "attribute" and bracket is None:
                continue  # not the attribute command: Lean would not parse it
            content = _bracketed(code, bracket.end() if bracket else end)
            if content is None:
                return word
            for name in _TOKEN.findall(content):
                if (
                    name in _CODE_ATTRIBUTES
                    or name.startswith("builtin_")
                    or name.endswith(_CODE_ATTRIBUTE_SUFFIXES)
                ):
                    return f"@[{name}]" if word == "@[" else f"attribute [{name}]"
        elif word == "set_option":
            option = _OPTION.match(code, end)
            name = option.group(1) if option else ""
            if name not in HEADER_OPTIONS and not name.startswith(HEADER_OPTION_PREFIXES):
                return f"set_option {name}".rstrip()
        elif word in _NOTATION:
            if not _LOCAL.search(code, max(0, match.start() - 64), match.start()):
                return word
        elif (
            word in _RUNS_CODE
            or word.startswith(_REGISTERS)
            or not _META_NAMESPACES.isdisjoint(word.split("."))
        ):
            return word
    escaped = _ESCAPED_META.search(body)
    return escaped.group() if escaped else None


def _refused_module(module, command):
    return HarnessError(
        "COMMONS_MODULE_REFUSED",
        f"{module} holds {command}, which no published module may hold.",
        status=422,
        details={"module": module, "command": command},
        remediation=_REPUBLISH,
    )


_REPUBLISH = (
    "Republish the module without #exit, without commands or attributes that run code or "
    "extend syntax (only local notation, and set_option only for the options a node header "
    "may set), and with every end matching a namespace or section it opened; or do not "
    "import it."
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
        else a ``sorry`` stub of its elaborated Lean statement. A source or statement
        stored before the publication gate that the gate refuses is refused here, so it is
        never inlined (``refused_command``)."""
        row = self._module_node(session, name, actor, experiment_id)
        node, source = row.payload, row.payload.get("lean_source")
        digest = _statement_digest(node)
        if source is not None:
            found = Module(
                name,
                row.id,
                self.artifacts.get(source["sha256"]).decode("utf-8"),
                _effective_rank(source, digest),
                source["sha256"],
                source["artifact_id"],
                source["branch_id"],
                stale=_stale(source, digest),
            )
        elif node.get("lean_statement") is not None and node.get("lean_elaborated"):
            header, statement = node.get("lean_header") or "", node["lean_statement"]
            stub = f"{header}\n\ntheorem {node['lean_name']} {statement} := sorry\n"
            found = Module(name, row.id, stub, "stub")
        else:
            found = None
        if found is not None:
            command = refused_command(found.source)
            if command is not None:
                raise _refused_module(name, command)
            return found
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

    def node_source_state(self, node_id, actor) -> tuple[dict, str]:
        """A commons node's payload and its ``source_state``, its imports read in the same
        session: a scoped recruit ends on it (``scope_ending``)."""
        with self.db.sessions() as session:
            row = self._get(session, "commons_node", node_id, actor)
            node = copy.deepcopy(row.payload)
            return node, source_state(node, Closures.reading(session, node["experiment_id"]))

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
        against), ``imports`` (``[{module, node_id, sha256}]``, each a depends_on edge) and
        ``closure`` (``[{node_id, sha256}]``, every module the check inlined; ``Closures``).
        A source whose imports reach the node through the stored sources' imports is refused
        (``imports_own_module``): published, the module would import itself. So is one that
        holds what no published module may (``refused_command``), whoever calls.
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
            content = self.artifacts.get(artifact.payload["sha256"])
            command = refused_command(content.decode("utf-8", errors="replace"))
            if command is not None:
                # Every importer would run it (the publication gate, whoever calls).
                refused = {"recorded": False, "module": module, "reason": "refused_command"}
                return {**refused, "command": command}
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
            state = source_state(node, Closures.reading(session, experiment.id))
            held = blocking_rank(node, rank, actor.branch_id, state)
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
                "closure": record.get("closure"),
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
                and state not in COMPLETE_RANKS
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
            # A stale source (of an older statement, or whose imports changed) is none: the
            # new one is a first publication.
            fresh = replaced and state in RANKS
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
