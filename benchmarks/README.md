# Unqualified algebra-prerequisite fixtures

The separate [physics inventory](physics/README.md) now supplies actual mathematical-physics
targets and review tooling. The scope and status below apply only to this original registry.

The registry contains 40 original local candidate tasks and 20 altered cases. All
remain pending expert review and uncompiled. They are tiny rational/component
prerequisites for the two research programs, not validated physics problems or
novel research results.

Reproduce the JSON registry and its Markdown provenance source with:

```sh
.venv/bin/python benchmarks/build_registry.py
```

The generator never invokes Lean. Source assumptions, proposed reference candidates,
negative expectations, family splits and provenance are recorded explicitly. Refer
to [SCIENCE.md](../docs/SCIENCE.md) for the loader, target-only discovery export,
qualification gate, and the limits of these fixtures.

The full registry and source material are evaluator inputs. Discovery workers should
receive only a scoped `discovery_tasks(...)` export and no access to reference files.
