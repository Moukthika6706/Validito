#!/bin/sh
# Waits for MySQL, applies migrations (api only), seeds demo data, then starts the service.
set -e

wait_for_db() {
  host="${MYSQL_HOST:-mysql}"; port="${MYSQL_PORT:-3306}"
  echo "waiting for MySQL at $host:$port ..."
  for i in $(seq 1 60); do
    if nc -z "$host" "$port" 2>/dev/null; then echo "MySQL is up"; return 0; fi
    sleep 2
  done
  echo "MySQL did not become ready in time" >&2
  exit 1
}

case "$1" in
  api)
    wait_for_db
    alembic upgrade head
    if [ "${SEED_DEMO_DATA:-true}" = "true" ]; then
      python scripts/make_samples.py >/dev/null 2>&1 || true
      python scripts/seed.py ${SEED_SAMPLES:+--samples} || echo "seed skipped"
    fi
    exec uvicorn app.main:app --host 0.0.0.0 --port 8000 ${UVICORN_EXTRA_ARGS}
    ;;
  worker)
    wait_for_db
    # Give the api container a moment to run migrations before the worker touches the DB.
    sleep 5
    exec celery -A app.workers.celery_app worker \
      --loglevel=info \
      --concurrency="${CELERY_CONCURRENCY:-2}" \
      -Q "${CELERY_QUEUES:-extraction,validation,default}"
    ;;
  *)
    exec "$@"
    ;;
esac
