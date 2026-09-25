import pytest

from physharness.science import NumericalRecord


def _record(**changes):
    data = dict(
        quantity="energy",
        value="1.25",
        absolute_error=None,
        precision_bits=53,
        method="sample mean",
        seed=7,
        input_sha256="a" * 64,
        environment_digest="b" * 64,
        tool_versions={"python": "3.11.2", "numpy": "1.24.2"},
        assumptions=[],
        error_interpretation="unknown",
    )
    return NumericalRecord(**{**data, **changes})


def test_unknown_error_is_explicit_and_cannot_masquerade_as_a_bound():
    assert _record().absolute_error is None
    with pytest.raises(ValueError):
        _record(error_interpretation="reported_bound")
    with pytest.raises(ValueError):
        _record(absolute_error="0.0")
