FROM physharness-formal:physics433
USER 0:0
WORKDIR /opt/sources/physlib
COPY DeclarationAudit.lean /opt/verifier/DeclarationAudit.lean
RUN lake --offline env lean /opt/verifier/DeclarationAudit.lean > /opt/verifier/metadata/declarations-kernel.txt
USER 65532:65532
WORKDIR /work
