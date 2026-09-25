import pytest

from physharness.orchestration.workspace_tools import validated_lean_imports


def test_lean_imports_accept_compiled_library_module_names():
    assert validated_lean_imports(["Mathlib", "QuantumInfo.States.Mixed.MState"]) == [
        "Mathlib",
        "QuantumInfo.States.Mixed.MState",
    ]


@pytest.mark.parametrize("bad", ["Mathlib\n#eval 1", "../Mathlib", "", "Foo--Bar"])
def test_lean_imports_reject_source_injection_and_paths(bad):
    with pytest.raises(ValueError):
        validated_lean_imports([bad])
