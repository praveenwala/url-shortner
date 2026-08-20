#!/usr/bin/env bash
#
# Build the agent test sandbox images (provisioning step, research R15).
#
# This is deliberately an operator action, not something the runtime can do.
# `run_tests` only ever *checks* whether an image exists; a missing image is a
# typed SandboxUnavailable failure that safe-stops the run. An agent therefore
# cannot cause an image build, and cannot influence what is inside one.
#
# Usage:  ops/sandbox/build-images.sh [orchestrator|shortener|console|all]
#
# The images contain dependencies only — no project source, no secrets, no
# credentials, no git history. Project code arrives at run time as a disposable
# copy mounted at /work.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
readonly SCRIPT_DIR REPO_ROOT

build() {
  local surface="$1"
  local tag="agent-sandbox/${surface}:latest"
  printf '==> building %s\n' "$tag"
  docker build \
    --file "$SCRIPT_DIR/Dockerfile.${surface}" \
    --tag "$tag" \
    "$REPO_ROOT"
  printf '==> built %s\n' "$tag"
}

main() {
  command -v docker >/dev/null 2>&1 || { echo "docker not found on PATH" >&2; exit 1; }
  docker info >/dev/null 2>&1 || { echo "docker daemon is not running" >&2; exit 1; }

  case "${1:-all}" in
    orchestrator|shortener|console) build "$1" ;;
    all) build orchestrator; build shortener; build console ;;
    *) echo "usage: build-images.sh [orchestrator|shortener|console|all]" >&2; exit 1 ;;
  esac
  printf '==> done\n'
  docker images --filter reference='agent-sandbox/*' \
    --format '    {{.Repository}}:{{.Tag}}  {{.Size}}'
}

main "$@"
