FROM physharness-formal:physics433-audited
USER 0:0
COPY prepare_lake.py record_build.py /opt/verifier/
WORKDIR /opt/sources/physlib
RUN python3 /opt/verifier/prepare_lake.py && lake --offline --no-build build Physlib.ClassicalMechanics.HarmonicOscillator.Basic QuantumInfo.States.Pure.Qubit QuantumInfo.States.Mixed.MState && python3 /opt/verifier/record_build.py && lake --offline env lean /opt/verifier/DeclarationAudit.lean > /opt/verifier/metadata/declarations-kernel.txt
USER 65532:65532
WORKDIR /work
