# Historical 2 GiB verifier evidence

These files preserve the initial engineering runs on image
`sha256:82497fa412f10a76e515ddc8590f1c387a8383c8b99b1cd215261f6a11151246`
with the former 2 GiB / 2 CPU resource limits. Core and library controls passed;
the full physics suites stopped after memory-limit kills. These are execution
failures, not mathematical rejections. The VM kernel reported `CONSTRAINT_MEMCG`
for the killed `comparator` and `lean4export` processes.

The recorded scope and pending review packet belong to the implementation at
collection time. Subsequent resource-policy changes invalidate their applicability
to the current deployment. They are retained as historical evidence and are not
rewritten or promoted to current qualification. No human approval was issued.
