"""Bounded exact arithmetic checks plus uncompiled Lean proof candidates.

The Python implementation is not a Lean kernel and cannot issue proof receipts.
Expressions are a JSON data language, never eval(), source code, or shell input.
"""

import hashlib
import json
import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from .records import ComputationResult, LeanObligation

Polynomial = dict[tuple[int, ...], Fraction]


class CertificateError(ValueError):
    def __init__(self, message: str, code: str = "invalid_certificate"):
        super().__init__(message)
        self.code = code


@dataclass
class Budget:
    operations: int = 0
    nodes: int = 0

    def consume(self, count: int = 1):
        self.operations += count
        if self.operations > 100_000:
            raise CertificateError(
                "Polynomial expansion exceeds 100000 operations.", "certificate_limit"
            )


def rational(value: Any) -> Fraction:
    if type(value) is int:
        if value.bit_length() > 4096:
            raise CertificateError("Integer exceeds 4096 bits.", "certificate_limit")
        return Fraction(value)
    if not isinstance(value, str) or len(value) > 1024:
        raise CertificateError("Coefficients must be exact integers or rational strings.")
    if not re.fullmatch(r"-?\d+(?:/[1-9]\d*)?", value):
        raise CertificateError("Use an integer or numerator/positive-denominator string.")
    return Fraction(value)


def lean_rat(value: Fraction) -> str:
    return f"(({value.numerator} : ℚ) / {value.denominator})"


def bounded(poly: Polynomial) -> Polynomial:
    poly = {powers: value for powers, value in poly.items() if value}
    if len(poly) > 4096 or any(sum(p) > 128 for p in poly):
        raise CertificateError("Polynomial term or degree limit exceeded.", "certificate_limit")
    if any(
        max(abs(v.numerator).bit_length(), v.denominator.bit_length()) > 8192 for v in poly.values()
    ):
        raise CertificateError("Expanded rational exceeds 8192 bits.", "certificate_limit")
    return poly


def add(left: Polynomial, right: Polynomial, budget: Budget) -> Polynomial:
    out = dict(left)
    budget.consume(len(right))
    for powers, value in right.items():
        out[powers] = out.get(powers, Fraction(0)) + value
    return bounded(out)


def multiply(left: Polynomial, right: Polynomial, budget: Budget) -> Polynomial:
    budget.consume(len(left) * len(right))
    out = {}
    for p, a in left.items():
        for q, b in right.items():
            powers = tuple(x + y for x, y in zip(p, q, strict=True))
            out[powers] = out.get(powers, Fraction(0)) + a * b
    return bounded(out)


def normalize(node: Any, variables: list[str], budget: Budget, depth: int = 0):
    budget.nodes += 1
    if depth > 32 or budget.nodes > 512:
        raise CertificateError("Expression nesting or node limit exceeded.", "certificate_limit")
    if not isinstance(node, dict):
        raise CertificateError("Each expression must be a tagged JSON object.")
    op = node.get("op")
    if not isinstance(op, str):
        raise CertificateError("Expression operation must be a string tag.")
    zero = (0,) * len(variables)
    if op == "const" and set(node) == {"op", "value"}:
        value = rational(node["value"])
        return bounded({zero: value}), lean_rat(value)
    if op == "var" and set(node) == {"op", "name"}:
        name = node["name"]
        if name not in variables:
            raise CertificateError("Expression contains an undeclared variable.")
        index = variables.index(name)
        return {tuple(int(i == index) for i in range(len(variables))): Fraction(1)}, f"v{index}"
    if op in {"add", "mul"} and set(node) == {"op", "args"}:
        args = node["args"]
        if not isinstance(args, list) or not 1 <= len(args) <= 128:
            raise CertificateError("Add/mul requires 1–128 expression arguments.")
        out = {} if op == "add" else {zero: Fraction(1)}
        source = []
        for child in args:
            poly, term = normalize(child, variables, budget, depth + 1)
            out = add(out, poly, budget) if op == "add" else multiply(out, poly, budget)
            source.append(term)
        return out, "(" + (" + " if op == "add" else " * ").join(source) + ")"
    if op == "pow" and set(node) == {"op", "base", "exponent"}:
        exponent = node["exponent"]
        if type(exponent) is not int or exponent < 0:
            raise CertificateError("Polynomial exponents must be nonnegative integers.")
        if exponent > 64:
            raise CertificateError("Exponent exceeds 64.", "certificate_limit")
        base, term = normalize(node["base"], variables, budget, depth + 1)
        out = {zero: Fraction(1)}
        for _ in range(exponent):
            out = multiply(out, base, budget)
        return out, f"({term} ^ {exponent})"
    raise CertificateError("Unknown operation or unexpected expression fields.")


def input_digest(value: Any) -> str | None:
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    except (TypeError, ValueError, RecursionError):
        return None
    if len(raw) > 1_000_000:
        return None
    return hashlib.sha256(raw).hexdigest()


def obligation(statement: str, tactic: str, mapping: dict[str, str] | None = None):
    mapping = mapping or {}
    binders = " ".join(f"({name} : ℚ)" for name in mapping.values())
    source = (
        "import Mathlib\n\n-- Uncompiled candidate; requires independent verification.\n"
        f"theorem certificate {binders} :\n    {statement} := by\n  {tactic}\n"
    )
    if len(source) > 500_000:
        raise CertificateError("Generated obligation exceeds source limit.", "certificate_limit")
    return LeanObligation(
        source=source,
        source_sha256=hashlib.sha256(source.encode()).hexdigest(),
        variable_mapping=mapping,
    )


def failure(error: CertificateError, digest: str | None) -> ComputationResult:
    return ComputationResult(
        status="blocked",
        code=error.code,
        message=str(error),
        remediation="Submit a smaller, well-formed certificate with exact rational values.",
        input_sha256=digest,
    )


def check_polynomial_identity(variables: list[str], left: Any, right: Any) -> ComputationResult:
    digest = input_digest(
        {"kind": "polynomial_identity", "variables": variables, "left": left, "right": right}
    )
    try:
        if digest is None:
            raise CertificateError("Certificate is not bounded JSON data.", "certificate_limit")
        if (
            not isinstance(variables, list)
            or not 1 <= len(variables) <= 16
            or any(
                not isinstance(v, str) or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,31}", v)
                for v in variables
            )
            or len(set(variables)) != len(variables)
        ):
            raise CertificateError("Declare 1–16 distinct simple variable names.")
        budget = Budget()
        lhs, left_source = normalize(left, variables, budget)
        rhs, right_source = normalize(right, variables, budget)
        residual = add(lhs, {p: -v for p, v in rhs.items()}, budget)
        proof = obligation(
            f"{left_source} = {right_source}", "ring", {v: f"v{i}" for i, v in enumerate(variables)}
        )
        return ComputationResult(
            status="refuted" if residual else "checked_computation",
            code="polynomial_mismatch" if residual else "exact_polynomial_identity",
            message="Exact coefficient comparison completed over the rationals.",
            remediation="Submit the generated candidate to the independent Lean verifier.",
            input_sha256=digest,
            obligation=proof,
            diagnostics={
                "scope": "the submitted rational polynomial identity",
                "residual": [
                    {"powers": list(p), "coefficient": str(v)} for p, v in sorted(residual.items())
                ],
                "operations": budget.operations,
            },
        )
    except CertificateError as exc:
        return failure(exc, digest)


def matrix(value: Any) -> list[list[Fraction]]:
    if not isinstance(value, list) or not 1 <= len(value) <= 16:
        raise CertificateError("Matrix must contain 1–16 rows.")
    if any(not isinstance(row, list) or not 1 <= len(row) <= 16 for row in value):
        raise CertificateError("Matrix rows must contain 1–16 entries.")
    if len({len(row) for row in value}) != 1:
        raise CertificateError("Matrix must be rectangular.")
    return [[rational(entry) for entry in row] for row in value]


def check_matrix_factorization(target: Any, left: Any, right: Any) -> ComputationResult:
    digest = input_digest(
        {"kind": "matrix_factorization", "target": target, "left": left, "right": right}
    )
    try:
        if digest is None:
            raise CertificateError("Certificate is not bounded JSON data.", "certificate_limit")
        expected, a, b = matrix(target), matrix(left), matrix(right)
        if len(a[0]) != len(b) or len(expected) != len(a) or len(expected[0]) != len(b[0]):
            raise CertificateError("Matrix dimensions do not describe target = left × right.")
        equations = []
        mismatch = None
        for i in range(len(a)):
            for j in range(len(b[0])):
                value = sum((a[i][k] * b[k][j] for k in range(len(b))), Fraction(0))
                if value != expected[i][j] and mismatch is None:
                    mismatch = {
                        "row": i,
                        "column": j,
                        "actual": str(value),
                        "expected": str(expected[i][j]),
                    }
                terms = [f"({lean_rat(a[i][k])} * {lean_rat(b[k][j])})" for k in range(len(b))]
                equations.append("(" + " + ".join(terms) + f" = {lean_rat(expected[i][j])})")
        proof = obligation(" ∧\n    ".join(equations), "norm_num")
        return ComputationResult(
            status="refuted" if mismatch else "checked_computation",
            code="matrix_mismatch" if mismatch else "exact_matrix_factorization",
            message="Every entry was compared using exact rational arithmetic.",
            remediation="Submit the generated candidate to the independent Lean verifier.",
            input_sha256=digest,
            obligation=proof,
            diagnostics={"scope": "the submitted rational matrix product", "mismatch": mismatch},
        )
    except CertificateError as exc:
        return failure(exc, digest)
