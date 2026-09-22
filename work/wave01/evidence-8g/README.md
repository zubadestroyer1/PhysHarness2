# Wave 0/1 current 8 GiB evidence

This directory retains observations for the consolidated image
`sha256:84deccc518a7aa5ce916d15236dac5ae416a5288449bd8620a2c8bb374c24b67`.
The final source scope is [scope-final.json](scope-final.json), canonical SHA-256
`e8f8c011e29242aa16f7464522b061545ac189f392c729655c57183a578ddb42`.
These reports must not be attributed to the historical 2 GiB image or scope.

The current **final control set** comprises [regressions-final.json](regressions-final.json)
and [regressions-final.xml](regressions-final.xml), the four `core-*-final.json` and
`library-*-final.json` reports, and [fixed-boundary-final.json](fixed-boundary-final.json).
It records 24 expected core/library outcomes across both kernel modes, 16 fixed
boundary observations, and 224 passed scoped host regressions with one conditional
PostgreSQL skip. [QUALIFICATION_REVIEW.md](QUALIFICATION_REVIEW.md) and
[qualification-review.json](qualification-review.json) assess this final control set:
all 10 mechanical checks are `satisfied`, while deployment approval is pending and
`production_qualified` is false. Human scientific review remains separate.

Earlier `scope.json`, `regressions.json`/`regressions.xml`, core/library reports
without `-final`, `fixed-boundary.json`, and `focused-independent.json` are retained
preliminary observations. They do not substitute for the final control set. The
full 60-case physics reports and their assessment are still running or pending;
no full-suite outcome is claimed here.
