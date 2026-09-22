#!/bin/sh
set -eu
: "${POSTGRES_SEEDS:?missing PostgreSQL host}"
: "${POSTGRES_USER:?missing PostgreSQL user}"
: "${SQL_PASSWORD:?missing PostgreSQL password}"
for database in temporal temporal_visibility; do
  temporal-sql-tool --plugin postgres12 --ep "$POSTGRES_SEEDS" \
    -u "$POSTGRES_USER" -p "${DB_PORT:-5432}" --db "$database" setup-schema -v 0.0
done
temporal-sql-tool --plugin postgres12 --ep "$POSTGRES_SEEDS" \
  -u "$POSTGRES_USER" -p "${DB_PORT:-5432}" --db temporal \
  update-schema -d /etc/temporal/schema/postgresql/v12/temporal/versioned
temporal-sql-tool --plugin postgres12 --ep "$POSTGRES_SEEDS" \
  -u "$POSTGRES_USER" -p "${DB_PORT:-5432}" --db temporal_visibility \
  update-schema -d /etc/temporal/schema/postgresql/v12/visibility/versioned
