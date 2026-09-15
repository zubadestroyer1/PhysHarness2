"""Scientific evidence adapters with no proof-acceptance authority."""

from .benchmarks import BenchmarkRegistry, BenchmarkTask, load_benchmarks
from .certificates import check_matrix_factorization, check_polynomial_identity
from .records import ComputationResult, LeanObligation, NumericalRecord

__all__ = [
    "BenchmarkRegistry",
    "BenchmarkTask",
    "ComputationResult",
    "LeanObligation",
    "NumericalRecord",
    "check_matrix_factorization",
    "check_polynomial_identity",
    "load_benchmarks",
]
