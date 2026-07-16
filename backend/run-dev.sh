#!/bin/sh
# Dev-mode backend launcher with --reload, so a source edit takes effect without
# anyone manually killing/restarting the shared uvicorn process on :8420 --
# filed after repeated uncoordinated SIGKILL-restarts (by dispatched agents AND
# by hand) collided and produced spurious "address already in use" churn.
set -e
cd "$(dirname "$0")"
exec env PANEL_READONLY=1 \
  LEDGER_PG_URI="host=192.168.122.1 dbname=toy" \
  LEDGER_SCHEMA=experience \
  LEDGER_KERNEL_SCHEMA=experience_kernel \
  LED_BIN="$(readlink -f ../led)" \
  ../venv/bin/python3 -m uvicorn app:app --host 0.0.0.0 --port 8420 --reload
