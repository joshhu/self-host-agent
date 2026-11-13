#!/bin/bash
# Run a command as root inside the worker VM through the Proxmox guest agent.
# stdout/stderr and the exit code come back. Pass -i first to forward stdin.
#   scripts/vm_exec.sh cat /workspace/output/report.md
#   scripts/vm_exec.sh -i python3 - --out /srv/ap < data/generate.py
set -euo pipefail
cd "$(dirname "$0")/.."
source .env
stdin=0
if [ "${1:-}" = "-i" ]; then stdin=1; shift; fi
quoted=$(printf '%q ' "$@")
decode='
import json, sys
r = json.load(sys.stdin)
def fix(text):  # the guest agent returns UTF-8 bytes as one character each
    try:
        return text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
sys.stdout.write(fix(r.get("out-data", "")))
sys.stderr.write(fix(r.get("err-data", "")))
sys.exit(r.get("exitcode", 1))'
remote="qm guest exec $PVE_VMID --pass-stdin $stdin --timeout 120 -- $quoted"
if [ "$stdin" = 1 ]; then
  eval "$PVE_SSH" '"$remote"' | python3 -c "$decode"
else
  eval "$PVE_SSH" '"$remote"' < /dev/null | python3 -c "$decode"
fi
