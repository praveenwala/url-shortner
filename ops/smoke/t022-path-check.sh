#!/usr/bin/env bash
# Technical pre-flight for the HUMAN T022 usability timing run.
#
# This proves the create → resolve → 302 → destination path works against a
# LIVE server. It is deliberately NOT the T022 observation: SC-001 requires an
# untrained person to be timed doing this by hand, and no script can stand in
# for that. Run this first so a failed timing run is never caused by a broken
# environment.
#
# Usage: ops/smoke/t022-path-check.sh [base-url] [destination]
set -euo pipefail

BASE="${1:-http://localhost:8080}"
DESTINATION="${2:-https://www.google.com}"
CLIENT="t022-preflight"
fail() { echo "  [FAIL] $*"; exit 1; }

echo "T022 technical pre-flight against ${BASE}"

# --- create ------------------------------------------------------------------
# `|| true` then an explicit check: with `set -e` a refused connection would
# otherwise abort the script silently, which reads as "nothing went wrong".
created=$(curl -s -w '\n%{http_code}' -X POST "${BASE}/v1/links" \
  -H "Content-Type: application/json" -H "X-Client-Id: ${CLIENT}" \
  -d "{\"destination\":\"${DESTINATION}\"}" || true)
[ -n "$created" ] || fail "no response from ${BASE} — is the shortener running?"
status=$(printf '%s' "$created" | tail -n1)
body=$(printf '%s' "$created" | sed '$d')
[ "$status" = "201" ] || fail "create returned HTTP ${status}: ${body}"

# The code must come from the response. A hard-coded or guessed code would make
# every check below meaningless, so it is parsed and shape-checked.
code=$(printf '%s' "$body" | sed -n 's/.*"code":"\([^"]*\)".*/\1/p')
[ -n "$code" ] || fail "no code in create response: ${body}"
printf '%s' "$code" | grep -Eq '^[0-9A-Za-z]{7}$' || fail "code '${code}' is not 7 base-62 characters"
echo "  [PASS] create            HTTP 201, code=${code}"

# --- resolve, without following ----------------------------------------------
headers=$(curl -s -D - -o /dev/null "${BASE}/${code}")
header_value() { printf '%s' "$headers" | grep -i "^$1:" | head -1 | cut -d: -f2- | tr -d '\r' | sed 's/^ *//'; }

printf '%s' "$headers" | head -1 | grep -q ' 302' || fail "expected 302, got: $(printf '%s' "$headers" | head -1)"
echo "  [PASS] resolve           HTTP 302"

expect() {
  local name="$1" want="$2" got; got=$(header_value "$name")
  [ "$got" = "$want" ] || fail "${name}: expected '${want}', got '${got}'"
  echo "  [PASS] ${name}$(printf '%*s' $((17 - ${#name})) '')${got}"
}
expect "Location"      "${DESTINATION}"
expect "Cache-Control" "no-store, no-cache, must-revalidate"
expect "Pragma"        "no-cache"
expect "Expires"       "0"

# --- follow it for real -------------------------------------------------------
final=$(curl -sL -o /dev/null -w '%{url_effective} %{http_code}' --max-time 20 "${BASE}/${code}" || true)
echo "  [INFO] followed          ${final}"

# --- a code that was never issued must not resolve ----------------------------
unknown=$(curl -s -o /dev/null -w '%{http_code}' "${BASE}/ZZfake9")
[ "$unknown" = "404" ] || fail "an unissued code returned HTTP ${unknown}, expected 404"
echo "  [PASS] unknown code      HTTP 404"

echo
echo "Technical path READY. The timed usability observation (SC-001) is a HUMAN task"
echo "and is not performed or recorded by this script."
