# Base image inputs must be digest-pinned (see infra/images.lock.json).
ARG PYTHON_IMAGE
ARG UV_IMAGE
FROM ${UV_IMAGE} AS uv
FROM ${PYTHON_IMAGE} AS application
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable --extra e2b --extra science \
    && useradd --uid 10001 --create-home --shell /usr/sbin/nologin harness \
    && mkdir -p /app/.state \
    && chown -R 10001:10001 /app/.state
COPY alembic.ini ./
COPY migrations ./migrations
COPY infra/certs/rds-global-bundle.pem /app/rds-ca.pem
ENV PATH="/app/.venv/bin:$PATH" TMPDIR=/app/.state
VOLUME ["/app/.state"]
USER 10001:10001
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "physharness.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
