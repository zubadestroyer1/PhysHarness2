"""Bounded, immutable native checkpoint graph with exact reconstruction.

The checkpoint manifest is the only mutable session pointer. Its references
form a tree of content-addressed artifacts, never a chain of earlier saves.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

from ..domain import canonical_json
from ..errors import HarnessError
from .types import RuntimeCheckpoint

FORMAT = "physharness.native_checkpoint.v2"
LEAF_BYTES = 16_384
LIST_PAGE = 8
INDEX_PAGE = 32
MAX_DEPTH = 32
MAX_NODES = 200_000
MAX_BYTES = 256_000_000
MAX_CHUNK_BYTES = 5_000_000


def _invalid(reason: str) -> HarnessError:
    return HarnessError("NATIVE_CHECKPOINT_INVALID", reason, status=500)


def is_manifest(value: Any) -> bool:
    return isinstance(value, dict) and value.get("format") == FORMAT


def references(node: Any) -> list[dict]:
    """Child references at structural positions only, for batched prefetch.

    Inline native values are never scanned; malformed nodes yield nothing
    here and are rejected by ``decode``.
    """
    if not isinstance(node, dict):
        return []

    def entry(item: Any) -> list[dict]:
        if isinstance(item, dict) and len(item) == 1:
            ref = next(iter(item.items()))
            if ref[0] in {"atom", "map", "ref"} and isinstance(ref[1], dict):
                return [ref[1]]
        return []

    kind = node.get("type")
    if kind == "checkpoint":
        return entry(node.get("session")) + entry(node.get("native_state"))
    if kind in {"sequence", "index"} and isinstance(node.get("children"), list):
        return [child for child in node["children"] if isinstance(child, dict)]
    if kind == "dict_branch" and isinstance(node.get("children"), dict):
        return [child for child in node["children"].values() if isinstance(child, dict)]
    items = node.get("items")
    if not isinstance(items, list):
        return []
    if kind == "list":
        return [ref for item in items for ref in entry(item)]
    if kind in {"dict", "dict_leaf"}:
        return [
            ref
            for item in items
            if isinstance(item, list) and len(item) == 2
            for ref in entry(item[1])
        ]
    return []


def encode(checkpoint: RuntimeCheckpoint, put: Callable[[str], dict]) -> dict:
    """Store chunks using ``put`` and return a small, versioned root manifest."""
    checkpoint.verify()
    if len(canonical_json(checkpoint.model_dump(mode="json")).encode("utf-8")) > MAX_BYTES:
        raise _invalid("Native checkpoint exceeds the write bound.")
    node_count = 0
    written: dict[str, bytes] = {}

    def store(node: dict) -> dict:
        nonlocal node_count
        node_count += 1
        if node_count > MAX_NODES:
            raise _invalid("Native checkpoint graph exceeds the node bound.")
        content = canonical_json(node)
        if len(content.encode("utf-8")) > MAX_CHUNK_BYTES:
            raise _invalid("Native checkpoint chunk exceeds the artifact bound.")
        artifact = put(content)
        written[artifact["id"]] = content.encode("utf-8")
        return {"artifact_id": artifact["id"], "sha256": artifact["sha256"]}

    def paged(kind: str, entries: list, page_size: int) -> dict:
        leaves = [
            store({"type": kind, "items": entries[i : i + page_size]})
            for i in range(0, len(entries), page_size)
        ]
        if not leaves:
            leaves = [store({"type": kind, "items": []})]
        level = 0
        while len(leaves) > INDEX_PAGE:
            leaves = [
                store({"type": "index", "level": level, "children": leaves[i : i + INDEX_PAGE]})
                for i in range(0, len(leaves), INDEX_PAGE)
            ]
            level += 1
            if level > MAX_DEPTH:
                raise _invalid("Native checkpoint index is too deep.")
        return store(
            {
                "type": "sequence",
                "kind": kind,
                "level": level,
                "children": leaves,
                "length": len(entries),
            }
        )

    def mapping(item: dict, depth: int) -> dict:
        entries = [
            (
                key,
                value(entry, depth + 1, atom_threshold=1024),
                hashlib.sha256(key.encode()).hexdigest(),
            )
            for key, entry in item.items()
        ]

        def branch(group: list, nibble: int) -> dict:
            if len(group) <= LIST_PAGE or nibble >= 64:
                return store(
                    {
                        "type": "dict_leaf",
                        "items": [[key, descriptor] for key, descriptor, _ in sorted(group)],
                    }
                )
            buckets: dict[str, list] = {}
            for entry in group:
                buckets.setdefault(entry[2][nibble], []).append(entry)
            return store(
                {
                    "type": "dict_branch",
                    "nibble": nibble,
                    "children": {
                        digit: branch(subgroup, nibble + 1)
                        for digit, subgroup in sorted(buckets.items())
                    },
                }
            )

        return branch(entries, 0)

    def value(item: Any, depth: int = 0, atom_threshold: int = LEAF_BYTES) -> dict:
        if depth > MAX_DEPTH:
            raise _invalid("Native checkpoint structure is too deep.")
        serialized = canonical_json(item)
        byte_size = len(serialized.encode("utf-8"))
        if byte_size <= atom_threshold:
            return {"inline": item}
        if byte_size <= LEAF_BYTES:
            return {"atom": store({"type": "atom", "value": item})}
        if isinstance(item, list):
            return {"ref": paged("list", [value(entry, depth + 1) for entry in item], LIST_PAGE)}
        if isinstance(item, dict):
            return {"map": mapping(item, depth)}
        if isinstance(item, str):
            # Character slices keep UTF-8 well formed; each segment is below
            # both the inline and artifact limits even for four-byte scalars.
            return {
                "ref": paged(
                    "text", [item[i : i + 2048] for i in range(0, len(item), 2048)], LIST_PAGE
                )
            }
        raise _invalid("Unsupported large native checkpoint value.")

    root = store(
        {
            "type": "checkpoint",
            "session": value(checkpoint.session.model_dump(mode="json")),
            "native_state": value(checkpoint.native_state),
        }
    )
    manifest = {
        "format": FORMAT,
        "version": 2,
        "session_id": checkpoint.session.id,
        "state_digest": checkpoint.state_digest,
        "root": root,
    }
    # Check the same graph and aggregate read bounds before publishing its pointer.
    if (
        decode(canonical_json(manifest).encode("utf-8"), lambda ref: written[ref["artifact_id"]])
        != checkpoint
    ):
        raise _invalid("Native checkpoint changed during encoding.")
    return manifest


def decode(
    raw: bytes, read: Callable[[dict], bytes], *, dependencies: set[str] | None = None
) -> RuntimeCheckpoint:
    """Read old full JSON or v2 graph, checking every edge and the exact state digest."""
    if len(raw) > MAX_BYTES:
        raise _invalid("Native checkpoint exceeds the read bound.")
    try:
        data = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as error:
        raise _invalid("Native checkpoint JSON is invalid.") from error
    if not is_manifest(data):
        try:
            checkpoint = RuntimeCheckpoint.model_validate(data)
            checkpoint.verify()
            return checkpoint
        except (ValueError, TypeError) as error:
            raise _invalid("Historical native checkpoint is invalid.") from error
    if (
        set(data) != {"format", "version", "session_id", "state_digest", "root"}
        or data["version"] != 2
    ):
        raise _invalid("Native checkpoint manifest version or fields are invalid.")
    nodes = 0
    total_bytes = len(raw)

    def node(ref: dict, depth: int) -> dict:
        nonlocal nodes, total_bytes
        if depth > MAX_DEPTH or nodes >= MAX_NODES:
            raise _invalid("Native checkpoint graph exceeds read bounds.")
        if not isinstance(ref, dict) or set(ref) != {"artifact_id", "sha256"}:
            raise _invalid("Native checkpoint reference is malformed.")
        artifact_id, digest = ref["artifact_id"], ref["sha256"]
        if not isinstance(artifact_id, str) or not isinstance(digest, str) or len(digest) != 64:
            raise _invalid("Native checkpoint reference identity is invalid.")
        content = read(ref)
        if not isinstance(content, bytes) or len(content) > MAX_CHUNK_BYTES:
            raise _invalid("Native checkpoint chunk exceeds the read bound.")
        if hashlib.sha256(content).hexdigest() != digest:
            raise _invalid("Native checkpoint chunk digest mismatch.")
        total_bytes += len(content)
        nodes += 1
        if total_bytes > MAX_BYTES:
            raise _invalid("Native checkpoint graph exceeds the byte bound.")
        if dependencies is not None:
            dependencies.add(artifact_id)
        try:
            return json.loads(content)
        except (ValueError, UnicodeDecodeError) as error:
            raise _invalid("Native checkpoint chunk JSON is invalid.") from error

    def value(entry: dict, depth: int) -> Any:
        if depth > MAX_DEPTH or not isinstance(entry, dict) or len(entry) != 1:
            raise _invalid("Native checkpoint value is invalid.")
        if "inline" in entry:
            if len(canonical_json(entry["inline"]).encode("utf-8")) > LEAF_BYTES:
                raise _invalid("Native checkpoint inline value exceeds its bound.")
            return entry["inline"]
        if "atom" in entry:
            atom = node(entry["atom"], depth)
            if (
                not isinstance(atom, dict)
                or set(atom) != {"type", "value"}
                or atom["type"] != "atom"
                or len(canonical_json(atom["value"]).encode("utf-8")) > LEAF_BYTES
            ):
                raise _invalid("Native checkpoint atom is invalid.")
            return atom["value"]
        if "map" in entry:

            def mapping(ref: dict, depth: int) -> dict:
                part = node(ref, depth)
                if not isinstance(part, dict):
                    raise _invalid("Native checkpoint mapping is invalid.")
                if part.get("type") == "dict_leaf":
                    if (
                        set(part) != {"type", "items"}
                        or not isinstance(part["items"], list)
                        or len(part["items"]) > LIST_PAGE
                    ):
                        raise _invalid("Native checkpoint mapping leaf is invalid.")
                    result = {}
                    for pair in part["items"]:
                        if (
                            not isinstance(pair, list)
                            or len(pair) != 2
                            or not isinstance(pair[0], str)
                            or pair[0] in result
                        ):
                            raise _invalid("Native checkpoint mapping entry is invalid.")
                        result[pair[0]] = value(pair[1], depth + 1)
                    return result
                if (
                    part.get("type") != "dict_branch"
                    or set(part) != {"type", "nibble", "children"}
                    or type(part["nibble"]) is not int
                    or not 0 <= part["nibble"] < 64
                    or not isinstance(part["children"], dict)
                    or not 1 <= len(part["children"]) <= 16
                    or any(
                        digit not in "0123456789abcdef" or len(digit) != 1
                        for digit in part["children"]
                    )
                ):
                    raise _invalid("Native checkpoint mapping branch is invalid.")
                result = {}
                for child in part["children"].values():
                    for key, item in mapping(child, depth + 1).items():
                        if key in result:
                            raise _invalid("Native checkpoint mapping has duplicate keys.")
                        result[key] = item
                return result

            return mapping(entry["map"], depth)
        if "ref" not in entry:
            raise _invalid("Native checkpoint value reference is invalid.")
        ref = entry["ref"]
        # The sequence kind is encoded in the referenced node. Read it once here;
        # the subsequent values() call must not re-read the same node.
        header = node(ref, depth)
        if not isinstance(header, dict) or header.get("type") != "sequence":
            raise _invalid("Native checkpoint value sequence is invalid.")
        kind = header.get("kind")
        return sequence(header, kind, depth)

    def sequence(header: dict, kind: str, depth: int) -> Any:
        if (
            kind not in {"list", "dict", "text"}
            or type(header.get("length")) is not int
            or header["length"] < 0
            or type(header.get("level")) is not int
            or header["level"] < 0
            or not isinstance(header.get("children"), list)
            or len(header["children"]) > INDEX_PAGE
        ):
            raise _invalid("Native checkpoint sequence is invalid.")

        def visit(ref: dict, level: int, depth: int) -> list:
            part = node(ref, depth)
            if level:
                if (
                    not isinstance(part, dict)
                    or part.get("type") != "index"
                    or part.get("level") != level - 1
                    or not isinstance(part.get("children"), list)
                    or not 1 <= len(part["children"]) <= INDEX_PAGE
                ):
                    raise _invalid("Native checkpoint index is invalid.")
                return [
                    entry
                    for child in part["children"]
                    for entry in visit(child, level - 1, depth + 1)
                ]
            if (
                not isinstance(part, dict)
                or part.get("type") != kind
                or not isinstance(part.get("items"), list)
                or len(part["items"]) > LIST_PAGE
            ):
                raise _invalid("Native checkpoint leaf is invalid.")
            return part["items"]

        items = [
            entry
            for child in header["children"]
            for entry in visit(child, header["level"], depth + 1)
        ]
        if len(items) != header["length"]:
            raise _invalid("Native checkpoint sequence count is invalid.")
        if kind == "list":
            return [value(item, depth + 1) for item in items]
        if kind == "text":
            if not all(isinstance(item, str) and len(item) <= 2048 for item in items):
                raise _invalid("Native checkpoint text page is invalid.")
            return "".join(items)
        result = {}
        for item in items:
            if (
                not isinstance(item, list)
                or len(item) != 2
                or not isinstance(item[0], str)
                or item[0] in result
            ):
                raise _invalid("Native checkpoint mapping page is invalid.")
            result[item[0]] = value(item[1], depth + 1)
        return result

    root = node(data["root"], 0)
    if (
        not isinstance(root, dict)
        or set(root) != {"type", "session", "native_state"}
        or root["type"] != "checkpoint"
    ):
        raise _invalid("Native checkpoint root is invalid.")
    try:
        checkpoint = RuntimeCheckpoint.model_validate(
            {
                "version": 1,
                "session": value(root["session"], 1),
                "native_state": value(root["native_state"], 1),
                "state_digest": data["state_digest"],
            }
        )
        checkpoint.verify()
    except (ValueError, TypeError) as error:
        raise _invalid("Native checkpoint reconstruction failed.") from error
    if checkpoint.session.id != data["session_id"]:
        raise _invalid("Native checkpoint session identity changed.")
    return checkpoint
