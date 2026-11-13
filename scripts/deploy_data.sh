#!/bin/bash
# Build the demo ERP database and invoice batch on the worker VM, read-only to the agent,
# and clear the previous run's output. The answer key is written locally to out/expected.json.
set -euo pipefail
cd "$(dirname "$0")/.."
scripts/vm_exec.sh -i python3 - --out /srv/ap < data/generate.py
scripts/vm_exec.sh sh -c 'chown -R root:root /srv/ap && chmod -R a+rX,go-w /srv/ap && rm -rf /workspace/output && ls -l /srv/ap /srv/ap/inbox | head -12'
python3 data/generate.py --out tmpcode/sample --expected out/expected.json > /dev/null
echo "answer key: out/expected.json"
