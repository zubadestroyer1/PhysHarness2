import importlib.util

import pytest


def api():
    assert importlib.util.find_spec("physharness.science"), "science is not implemented"
    from physharness import science

    return science


def c(value):
    return {"op": "const", "value": value}


def x(name="x"):
    return {"op": "var", "name": name}


def expr(op, *args):
    return {"op": op, "args": list(args)}


def test_exact_polynomial_expansion_with_rational_coefficients():
    left = {"op": "pow", "base": expr("add", x(), c("1/2")), "exponent": 2}
    right = expr("add", expr("mul", x(), x()), x(), c("1/4"))
    out = api().check_polynomial_identity(["x"], left, right)
    assert out.status == "checked_computation" and out.proof_status == "not_lean_proof"
    assert out.obligation.status == "uncompiled"
    assert out.obligation.required_imports == ["Mathlib"]
    assert "native_decide" not in out.obligation.source and "sorry" not in out.obligation.source


def test_polynomial_mismatch_reports_exact_residual():
    out = api().check_polynomial_identity(["x"], expr("add", x(), c("1/3")), x())
    assert out.status == "refuted"
    assert out.diagnostics["residual"] == [{"powers": [0], "coefficient": "1/3"}]


@pytest.mark.parametrize("bad", [0.1, True, "nan", "1/0", '__import__("os")'])
def test_inexact_or_invalid_coefficients_are_blocked(bad):
    out = api().check_polynomial_identity(["x"], c(bad), x())
    assert out.status == "blocked" and out.remediation


def test_unknown_variable_and_expansion_budget_are_blocked():
    assert api().check_polynomial_identity(["x"], x("y"), x()).status == "blocked"
    huge = {"op": "pow", "base": expr("add", x(), c(1)), "exponent": 1000000}
    assert api().check_polynomial_identity(["x"], huge, x()).code == "certificate_limit"


def test_malformed_operation_tags_and_cyclic_payloads_fail_closed():
    s = api()
    for tag in [[], {}, None]:
        assert s.check_polynomial_identity(["x"], {"op": tag}, x()).status == "blocked"
    cyclic = {"op": "add", "args": []}
    cyclic["args"].append(cyclic)
    assert s.check_polynomial_identity(["x"], cyclic, x()).status == "blocked"


def test_polynomial_coefficient_equality_is_not_finite_point_sampling():
    # x*(x-1) vanishes at both 0 and 1 but is not the zero polynomial.
    out = api().check_polynomial_identity(["x"], expr("mul", x(), expr("add", x(), c(-1))), c(0))
    assert out.status == "refuted"
    assert out.diagnostics["residual"] == [
        {"powers": [1], "coefficient": "-1"},
        {"powers": [2], "coefficient": "1"},
    ]


def test_polynomial_expansion_and_negative_fraction_signs():
    out = api().check_polynomial_identity(
        ["x", "y"],
        expr("mul", c("-2/3"), expr("add", x(), x("y"))),
        expr("add", expr("mul", c("-2/3"), x()), expr("mul", c("-2/3"), x("y"))),
    )
    assert out.status == "checked_computation"


def test_exact_rational_matrix_factorization_and_tamper():
    s = api()
    left = [["1/2", "1/3"], ["0", "2"]]
    right = [["2", "0"], ["3", "1"]]
    out = s.check_matrix_factorization([["2", "1/3"], ["6", "2"]], left, right)
    assert out.status == "checked_computation" and out.obligation.status == "uncompiled"
    bad = s.check_matrix_factorization([["2", "1/3"], ["6", "3"]], left, right)
    assert bad.status == "refuted"
    assert bad.diagnostics["mismatch"] == {"row": 1, "column": 1, "actual": "2", "expected": "3"}


@pytest.mark.parametrize(
    "target,left,right", [([], [], []), ([[1]], [[1, 2]], [[1]]), ([[1]], [[1.0]], [[1]])]
)
def test_bad_matrix_certificates_block(target, left, right):
    assert api().check_matrix_factorization(target, left, right).status == "blocked"


def test_numerical_record_requires_error_and_reproduction_metadata():
    s = api()
    record = dict(
        quantity="energy",
        value="0.125",
        absolute_error="0.00001",
        precision_bits=128,
        method="interval quadrature",
        seed=42,
        input_sha256="a" * 64,
        environment_digest="b" * 64,
        tool_versions={"python": "3.12"},
        assumptions=["fixed time step"],
    )
    assert s.NumericalRecord(**record).evidence_kind == "numerical_observation"
    for change in [
        {"absolute_error": "-1"},
        {"value": "NaN"},
        {"precision_bits": 0},
        {"tool_versions": {}},
    ]:
        with pytest.raises(ValueError):
            s.NumericalRecord(**{**record, **change})
