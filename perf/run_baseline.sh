#!/usr/bin/env bash
#
# Reproduce the URL-shortener load baseline (T098).
#
# Measures the PostgreSQL-only implementation against the approved target:
# 100 redirects/sec sustained, p95 < 150 ms, p99 < 400 ms.
#
# This measures; it does not tune. No application or schema change belongs in this
# script — that is the point of a baseline.
#
#   ops:  ./perf/run_baseline.sh
#
# Requires Docker, Java 21, and the project virtualenv at .venv.

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PY="$REPO/.venv/bin/python"
CONTAINER=shortener-perf
DB_PORT=55432
DSN="postgresql://shortener:perf-local-only@localhost:${DB_PORT}/shortener_db"
BASE_URL="http://localhost:8080"
CORPUS=100000
RATE=100
DURATION=120          # long enough that JIT and pool warm-up are not in the numbers
HOT_SHARE=0.7         # Profile B: 70% of traffic onto a small hot set
HOT_SIZE=5

export JAVA_HOME="${JAVA_HOME:-$(/usr/libexec/java_home -v 21)}"

cleanup() {
  [[ -n "${APP_PID:-}" ]] && kill "$APP_PID" 2>/dev/null || true
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
}
trap cleanup EXIT

echo "==> PostgreSQL"
docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
docker run -d --name "$CONTAINER" -p "${DB_PORT}:5432" \
  -e POSTGRES_DB=shortener_db -e POSTGRES_USER=shortener -e POSTGRES_PASSWORD=perf-local-only \
  postgres:16-alpine -c shared_preload_libraries=pg_stat_statements -c max_connections=200 >/dev/null
until docker exec "$CONTAINER" pg_isready -U shortener >/dev/null 2>&1; do sleep 1; done
docker exec -e PGPASSWORD=perf-local-only "$CONTAINER" \
  psql -U shortener -d shortener_db -qc "CREATE EXTENSION IF NOT EXISTS pg_stat_statements;"

echo "==> application"
(cd "$REPO/shortener" && mvn -B -q -DskipTests package)
SHORTENER_DB_URL="jdbc:postgresql://localhost:${DB_PORT}/shortener_db" \
SHORTENER_DB_USER=shortener SHORTENER_DB_PASSWORD=perf-local-only \
  "$JAVA_HOME/bin/java" -jar "$REPO/shortener/target/shortener-0.1.0-SNAPSHOT.jar" \
  > /tmp/shortener-perf.log 2>&1 &
APP_PID=$!
until curl -fsS "$BASE_URL/actuator/health" >/dev/null 2>&1; do sleep 1; done

echo "==> seeding ${CORPUS} links"
"$PY" "$REPO/perf/seed.py" --dsn "$DSN" --count "$CORPUS" --codes-out "$REPO/perf/results/codes.txt"

echo "==> warm-up (excluded from results)"
"$PY" "$REPO/perf/loadgen.py" --profile warmup --rate "$RATE" --duration 6 \
  --out "$REPO/perf/results/warmup.json" >/dev/null

echo "==> Profile A — nominal, broad distribution"
docker exec -e PGPASSWORD=perf-local-only "$CONTAINER" \
  psql -U shortener -d shortener_db -qtAXc "SELECT pg_stat_statements_reset();" >/dev/null
"$PY" "$REPO/perf/loadgen.py" --profile A-nominal --rate "$RATE" --duration "$DURATION" \
  --hot-share 0 --out "$REPO/perf/results/profile-a.json"

echo "==> Profile B — hot-link skew"
docker exec -e PGPASSWORD=perf-local-only "$CONTAINER" \
  psql -U shortener -d shortener_db -qtAXc "SELECT pg_stat_statements_reset();" >/dev/null
"$PY" "$REPO/perf/loadgen.py" --profile B-hot-skew --rate "$RATE" --duration "$DURATION" \
  --hot-share "$HOT_SHARE" --hot-size "$HOT_SIZE" --out "$REPO/perf/results/profile-b.json"

echo "==> exact-accounting check (SC-006 under load)"
docker exec -e PGPASSWORD=perf-local-only "$CONTAINER" psql -U shortener -d shortener_db -tAX -c \
  "SELECT (SELECT count(*) FROM redirect_event) events, (SELECT sum(redirect_count) FROM short_link) counted;"

echo "==> done — results in perf/results/"
