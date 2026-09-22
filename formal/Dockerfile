# Build from a separately audited, digest-pinned Linux toolchain image.
# No prebuilt qualified image is shipped with this repository.
ARG QUALIFIED_TOOLCHAIN_IMAGE
FROM ${QUALIFIED_TOOLCHAIN_IMAGE}
USER root
COPY src/physharness/verification/container_driver.py /opt/physharness/container_driver.py
RUN chmod 0555 /opt/physharness/container_driver.py
USER 65532:65532
ENTRYPOINT ["/usr/bin/python3", "/opt/physharness/container_driver.py"]
