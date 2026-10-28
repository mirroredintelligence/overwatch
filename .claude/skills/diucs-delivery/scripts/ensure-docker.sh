#!/usr/bin/env bash
# Start the Docker daemon if it is not running. The cloud container has no systemd, so
# `service docker start` fails; dockerd has to be started directly, and again after a restart.
# No-op when Docker is already up or is not installed. Neo4j tests need it (DEC-008).
set -u
if ! command -v dockerd >/dev/null 2>&1 || ! command -v docker >/dev/null 2>&1; then
  exit 0
fi
if docker info >/dev/null 2>&1; then
  echo "docker running"
  exit 0
fi
LOG="${TMPDIR:-/tmp}/dockerd.log"
nohup dockerd >"$LOG" 2>&1 &
for _ in $(seq 1 30); do
  if docker info >/dev/null 2>&1; then
    echo "docker started"
    exit 0
  fi
  sleep 2
done
echo "docker did not start; see $LOG" >&2
exit 1
