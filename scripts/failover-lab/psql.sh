#!/usr/bin/env bash
# psql contra la PostgreSQL del laboratorio (solo ese contenedor).
exec docker exec -i -e PGPASSWORD=lab-local-only-admin nexo-failover-lab-db-1 psql -U postgres -d nexoeventos -v ON_ERROR_STOP=1 -tA "$@"
