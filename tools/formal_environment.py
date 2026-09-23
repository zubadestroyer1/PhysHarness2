#!/usr/bin/env python3
"""Source provenance and lexical audit utilities; this module never executes Lean.

A successful audit identifies exact source bytes. It grants neither semantic approval
nor kernel/sandbox qualification. Build execution belongs inside the Linux builder.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path, PurePosixPath

SHA256 = re.compile(r"[0-9a-f]{64}\Z")
COMMIT = re.compile(r"[0-9a-f]{40}\Z")
NAME = re.compile(r"[A-Za-z0-9_-]+\Z")
MAX_ARCHIVE = 2_000_000_000
MAX_EXPANDED = 4_000_000_000


def sha256(path: Path) -> str:
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def check_sha(value: object) -> None:
    if not isinstance(value, str) or not SHA256.fullmatch(value):
        raise ValueError("missing or malformed SHA256")


def validate_lock(lock: dict) -> None:
    if lock.get("schema") != "physharness-formal-environment-v1":
        raise ValueError("unsupported lock schema")
    toolchain = f"leanprover/lean4:{lock['lean']['version']}"
    required = {"comparator", "lean4export", "landrun", "nanoda", "physlib", "mathlib"}
    if not required.issubset(lock["sources"]):
        raise ValueError("missing required source in environment lock")
    if set(lock["lean"]["archives"]) != {"amd64", "arm64"}:
        raise ValueError("Lean archive architecture pins must include amd64 and arm64")
    for name, source in lock["sources"].items():
        if not NAME.fullmatch(name):
            raise ValueError("unsafe source path")
        if not isinstance(source.get("revision"), str) or not COMMIT.fullmatch(source["revision"]):
            raise ValueError(f"invalid source revision: {name}")
        check_sha(source.get("archive_sha256"))
        expected = (
            source["repository"].replace("https://github.com/", "https://codeload.github.com/")
            + "/tar.gz/"
            + source["revision"]
        )
        if source["archive_url"] != expected or not expected.startswith(
            "https://codeload.github.com/"
        ):
            raise ValueError(f"archive URL must bind source revision: {name}")
        if (
            source.get("lean_toolchain") is not None
            and name in {"comparator", "lean4export", "physlib", "mathlib"}
            and source["lean_toolchain"] != toolchain
        ):
            raise ValueError(f"incompatible toolchain: {name}")
    for artifact in lock["lean"]["archives"].values():
        check_sha(artifact.get("sha256"))
        if not artifact["url"].startswith(
            "https://github.com/leanprover/lean4/releases/download/" + lock["lean"]["version"] + "/"
        ):
            raise ValueError("invalid Lean release URL")
    for image in lock["builder_images"].values():
        if not re.fullmatch(r"[a-z0-9/._:-]+@sha256:[0-9a-f]{64}", image):
            raise ValueError("builder image must be pinned by digest")
    for library in lock["libraries"].values():
        if library["source"] not in lock["sources"] or library["semantic_review"] != "not_reviewed":
            raise ValueError("source lock cannot grant semantic approval")


def download_verified(url: str, digest: str, output: Path) -> None:
    check_sha(digest)
    if output.exists() or output.is_symlink():
        if output.is_symlink() or not output.is_file() or sha256(output) != digest:
            raise ValueError(f"SHA256 mismatch in existing cache: {output}")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="formal-download-", dir=output.parent) as scratch:
        temporary = Path(scratch) / "archive.partial"
        with (
            urllib.request.urlopen(url, timeout=120) as response,
            temporary.open("xb") as destination,
        ):
            count = 0
            while chunk := response.read(1024 * 1024):
                count += len(chunk)
                if count > MAX_ARCHIVE:
                    raise ValueError("archive download exceeded byte limit")
                destination.write(chunk)
        if sha256(temporary) != digest:
            raise ValueError(f"SHA256 mismatch: {url}")
        temporary.replace(output)


def extract_verified(archive: Path, digest: str, destination: Path) -> None:
    """Verify first, validate all paths, extract into a fresh directory atomically."""
    check_sha(digest)
    if archive.is_symlink() or sha256(archive) != digest:
        raise ValueError(f"archive SHA256 mismatch: {archive}")
    if destination.exists() or destination.is_symlink():
        raise ValueError("archive destination must be fresh")
    with tarfile.open(archive, "r:gz") as stream:
        members = stream.getmembers()
        planned = []
        roots = set()
        names = set()
        total = 0
        for member in members:
            path = PurePosixPath(member.name)
            if path.is_absolute() or ".." in path.parts or not path.parts:
                raise ValueError("unsafe archive path")
            roots.add(path.parts[0])
            if len(path.parts) == 1:
                if not member.isdir():
                    raise ValueError("archive must contain one root directory")
                continue
            relative = Path(*path.parts[1:])
            if (
                relative in names
                or member.islnk()
                or not (member.isfile() or member.isdir() or member.issym())
            ):
                raise ValueError("unsupported or duplicate archive member")
            names.add(relative)
            if member.issym():
                target = PurePosixPath(member.linkname)
                # Internal relative symlinks are present in upstream documentation.
                stack = list(relative.parent.parts)
                if target.is_absolute():
                    raise ValueError("unsafe archive symlink")
                for piece in target.parts:
                    if piece == "..":
                        if not stack:
                            raise ValueError("unsafe archive symlink")
                        stack.pop()
                    elif piece != ".":
                        stack.append(piece)
            total += member.size
            if total > MAX_EXPANDED:
                raise ValueError("archive expansion exceeded byte limit")
            planned.append((member, relative))
        if len(roots) != 1:
            raise ValueError("archive must contain exactly one root")
        symlinks = {path for member, path in planned if member.issym()}
        if any(parent in symlinks for _, path in planned for parent in path.parents):
            raise ValueError("archive member descends through a symlink")
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="formal-source-", dir=destination.parent
        ) as temporary:
            staged = Path(temporary) / "source"
            staged.mkdir()
            for member, relative in planned:
                output = staged / relative
                output.parent.mkdir(parents=True, exist_ok=True)
                if member.isdir():
                    output.mkdir(exist_ok=True)
                elif member.issym():
                    output.symlink_to(member.linkname)
                else:
                    with stream.extractfile(member) as source, output.open("xb") as target:
                        shutil.copyfileobj(source, target)
                    output.chmod(0o755 if member.mode & 0o111 else 0o644)
            staged.rename(destination)


def mask_comments_and_strings(source: str) -> str:
    """Conservative lexical inventory, preserving line/column positions; not a parser."""
    result = list(source)
    position = depth = 0
    quoted = False
    while position < len(source):
        if depth:
            if source.startswith("/-", position):
                result[position : position + 2] = "  "
                depth += 1
                position += 2
            elif source.startswith("-/", position):
                result[position : position + 2] = "  "
                depth -= 1
                position += 2
            else:
                if source[position] != "\n":
                    result[position] = " "
                position += 1
        elif quoted:
            if source[position] == "\\":
                result[position : position + 2] = "  "
                position += 2
            else:
                quoted = source[position] != '"'
                if source[position] != "\n":
                    result[position] = " "
                position += 1
        elif source.startswith("--", position):
            end = source.find("\n", position)
            end = len(source) if end < 0 else end
            result[position:end] = " " * (end - position)
            position = end
        elif source.startswith("/-", position):
            depth = 1
            result[position : position + 2] = "  "
            position += 2
        elif source[position] == '"':
            quoted = True
            result[position] = " "
            position += 1
        else:
            position += 1
    if depth or quoted:
        raise ValueError("unterminated Lean comment or string in source audit")
    return "".join(result)


def audit_declarations(sources: Path, selection: dict) -> dict:
    result = {
        "schema": "physharness-declaration-audit-v1",
        "audit_kind": "lexical_source_inventory",
        "semantic_review": "not_reviewed",
        "kernel_check": "not_run",
        "sandbox_qualification": "not_run",
        "transitive_axiom_closure": "not_computed",
        "modules": [],
    }
    sources = sources.resolve()
    for requested in selection["modules"]:
        package, relative = requested["package"], PurePosixPath(requested["path"])
        if not NAME.fullmatch(package) or relative.is_absolute() or ".." in relative.parts:
            raise ValueError("unsafe source path")
        source_path = sources / package / str(relative)
        if any(
            part.is_symlink()
            for part in [source_path, *source_path.parents]
            if part.is_relative_to(sources) and part != sources
        ):
            raise ValueError("symlink in source audit path")
        if not source_path.is_file() or not source_path.resolve().is_relative_to(
            (sources / package).resolve()
        ):
            raise ValueError("missing or escaping source path")
        data = source_path.read_bytes()
        masked = mask_comments_and_strings(data.decode("utf-8"))
        found = {}
        pattern = (
            r"(?m)^\s*(?:(?:public|protected|private|noncomputable|unsafe|partial)\s+)*"
            r"(theorem|lemma|def|abbrev|structure|class|inductive|axiom)\s+([^\s(:{\[=]+)"
        )
        for match in re.finditer(pattern, masked):
            kind, name = match.groups()
            # Names are source spellings, not elaborated fully-qualified constants.
            found.setdefault(name, []).append(
                {"name": name, "kind": kind, "line": masked.count("\n", 0, match.start(1)) + 1}
            )
        declarations = []
        for name in requested["declarations"]:
            if name not in found or len(found[name]) != 1:
                raise ValueError(f"missing or ambiguous declaration {name} in {relative}")
            declarations.append(found[name][0])
        risks = {}
        for token in (
            "axiom",
            "sorry",
            "admit",
            "unsafe",
            "native_decide",
            "implemented_by",
            "extern",
        ):
            lines = sorted(
                {
                    masked.count("\n", 0, m.start()) + 1
                    for m in re.finditer(r"\b" + token + r"\b", masked)
                }
            )
            if lines:
                risks[token] = lines
        imports = re.findall(r"(?m)^\s*(?:(?:public|private)\s+)?import\s+([^\s]+)", masked)
        result["modules"].append(
            {
                "package": package,
                "path": str(relative),
                "source_sha256": hashlib.sha256(data).hexdigest(),
                "imports": imports,
                "declarations": declarations,
                "risk_tokens": risks,
            }
        )
    return result


def write_build_context(root: Path, destination) -> None:
    """Send required builder inputs and fixture sources, never arbitrary workspace data."""
    root = root.resolve()
    names = {
        "formal/Dockerfile",
        "formal/environment.lock.json",
        "formal/prepare_lake.py",
        "formal/record_build.py",
        "formal/DeclarationAudit.lean",
        "tools/formal_environment.py",
        "src/physharness/verification/container_driver.py",
        "src/physharness/verification/resource_policy.py",
    }
    generated = {
        ".lake",
        ".elan",
        ".git",
        ".venv",
        ".state",
        ".cache",
        "__pycache__",
        "node_modules",
    }
    for fixture_root in (root / "formal/smoke", root / "formal/adversarial"):
        for directory, directories, files in os.walk(fixture_root, followlinks=False):
            directories[:] = [
                name
                for name in directories
                if name not in generated and not (Path(directory) / name).is_symlink()
            ]
            for name in files:
                path = Path(directory) / name
                if path.suffix in {".lean", ".toml"} or name in {"cases.json", "lean-toolchain"}:
                    names.add(str(path.relative_to(root)))
    # Validate before emitting any bytes, including required source parent directories.
    for name in names:
        path = root / name
        if (
            not path.is_file()
            or path.is_symlink()
            or any(
                parent.is_symlink()
                for parent in path.parents
                if parent.is_relative_to(root) and parent != root
            )
        ):
            raise ValueError(f"build context requires regular source paths: {name}")
    # Buildx must recognize stdin within its short initial header peek. USTAR
    # avoids a leading PAX extension for filesystem subsecond timestamps.
    with tarfile.open(fileobj=destination, mode="w|", format=tarfile.USTAR_FORMAT) as context:
        for name in sorted(names):
            context.add(root / name, arcname=name, recursive=False)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lock", type=Path, default=Path("formal/environment.lock.json"))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("validate")
    sub.add_parser("build-context")
    fetch = sub.add_parser("fetch")
    fetch.add_argument("--cache", type=Path, required=True)
    fetch.add_argument("--packages", nargs="+")
    extract = sub.add_parser("extract")
    extract.add_argument("--cache", type=Path, required=True)
    extract.add_argument("--sources", type=Path, required=True)
    extract.add_argument("--packages", nargs="+")
    audit = sub.add_parser("audit")
    audit.add_argument("--cache", type=Path, required=True)
    audit.add_argument("--selection", type=Path, default=Path("formal/declarations.selection.json"))
    audit.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        lock = json.loads(args.lock.read_text())
        validate_lock(lock)
        if args.command == "build-context":
            write_build_context(args.lock.resolve().parent.parent, sys.stdout.buffer)
        elif args.command == "validate":
            print("Source lock is structurally valid; no qualification or review granted.")
        elif args.command in {"fetch", "extract"}:
            for name in args.packages or lock["sources"]:
                source = lock["sources"][name]
                path = args.cache / (name + ".tar.gz")
                if args.command == "fetch":
                    download_verified(source["archive_url"], source["archive_sha256"], path)
                else:
                    extract_verified(path, source["archive_sha256"], args.sources / name)
                print(f"{args.command}: {name} {source['revision']}", flush=True)
        else:
            selection = json.loads(args.selection.read_text())
            with tempfile.TemporaryDirectory(prefix="formal-audit-") as temporary:
                sources = Path(temporary)
                for name in sorted({m["package"] for m in selection["modules"]}):
                    extract_verified(
                        args.cache / (name + ".tar.gz"),
                        lock["sources"][name]["archive_sha256"],
                        sources / name,
                    )
                report = audit_declarations(sources, selection)
                report["source_lock_sha256"] = sha256(args.lock)
                report["selection_sha256"] = sha256(args.selection)
                report["source_revisions"] = {
                    name: lock["sources"][name]["revision"]
                    for name in sorted({m["package"] for m in selection["modules"]})
                }
                args.output.parent.mkdir(parents=True, exist_ok=True)
                with args.output.open("x") as output:
                    output.write(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
                print(
                    f"Wrote {len(report['modules'])} source modules; "
                    "kernel and semantic review remain unperformed."
                )
    except (ValueError, KeyError, OSError, tarfile.TarError) as error:
        parser.exit(1, f"formal environment blocked: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
