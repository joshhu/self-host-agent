"""Run one invoice-reconciliation session and show what the agent does.

This is the part a real system would run automatically (on a schedule, or when
invoices arrive). It talks to Anthropic's service; the agent's commands run on
the worker VM.

    uv run reconcile.py
"""

import json
import subprocess
import sys
import time
from pathlib import Path

import anthropic

ROOT = Path(__file__).parent
OUT = ROOT / "out"

TASK = (
    "Reconcile the invoice batch in /srv/ap/inbox against the ERP database, "
    "following the matching policy, and write the two output files."
)


def resource_id(kind: str) -> str:
    """Read the agent / environment ID that `ant apply` recorded in claude-lock.json."""
    lock = json.loads((ROOT / "claude-lock.json").read_text())
    return next(r["id"] for r in lock["resources"].values() if r["kind"] == kind)


def show(event) -> None:
    if event.type == "agent.tool_use":
        detail = event.input.get("command") or event.input.get("file_path") or json.dumps(event.input, ensure_ascii=False)
        first_line = detail.strip().splitlines()[0] if detail.strip() else ""
        print(f"  [{event.name}] {first_line[:110]}")
    elif event.type == "agent.message":
        for block in event.content:
            if block.type == "text":
                print(f"\n{block.text}\n")
    elif event.type == "session.error":
        print(f"  [error] {event.error}", file=sys.stderr)


def run_session(client: anthropic.Anthropic, on_event=show) -> str:
    """Start a session, send the task, and call on_event for each event until the agent is done."""
    session = client.beta.sessions.create(
        agent=resource_id("agent"),
        environment_id=resource_id("environment"),
        title="AP reconciliation",
    )
    print(f"session {session.id}")
    print(f"trace   https://platform.claude.com/workspaces/default/sessions/{session.id}\n")

    # Open the stream before sending, so no early event is missed.
    with client.beta.sessions.events.stream(session_id=session.id) as stream:
        client.beta.sessions.events.send(
            session_id=session.id,
            events=[{"type": "user.message", "content": [{"type": "text", "text": TASK}]}],
        )
        for event in stream:
            on_event(event)
            if event.type == "agent.tool_use" and getattr(event, "evaluated_permission", None) == "ask":
                # Nobody is watching this run, so a call that needs a human decision is refused.
                print("  -> needs approval; denied (unattended run)")
                client.beta.sessions.events.send(
                    session_id=session.id,
                    events=[{"type": "user.tool_confirmation", "tool_use_id": event.id, "result": "deny"}],
                )
            elif event.type == "session.status_idle" and event.stop_reason.type != "requires_action":
                break
            elif event.type == "session.status_terminated":
                break
    return session.id


def fetch(name: str) -> str:
    """Copy one output file from the worker VM. A backend inside the company network
    would read it directly; from this Mac it goes through the Proxmox host."""
    result = subprocess.run(
        [str(ROOT / "scripts" / "vm_exec.sh"), "cat", f"/workspace/output/{name}"],
        capture_output=True, text=True, check=True,
    )
    OUT.mkdir(exist_ok=True)
    (OUT / name).write_text(result.stdout, encoding="utf-8")
    return result.stdout


def main() -> None:
    client = anthropic.Anthropic()
    started = time.monotonic()
    run_session(client)
    print(f"finished in {time.monotonic() - started:.0f}s\n")

    invoices = json.loads(fetch("reconciliation.json"))["invoices"]
    fetch("report.md")
    for inv in invoices:
        mark = "OK  " if inv["decision"] == "approve" else "HOLD"
        print(f"{mark} {inv['file']:<10} {inv['total']:>9,}  {', '.join(inv['reasons'])}")
    approved = [i for i in invoices if i["decision"] == "approve"]
    held = [i for i in invoices if i["decision"] != "approve"]
    print(f"\n可付款 {len(approved)} 張，共 NT$ {sum(i['total'] for i in approved):,}")
    print(f"待審核 {len(held)} 張，共 NT$ {sum(i['total'] for i in held):,}")
    print(f"\n結果已存到 {OUT / 'reconciliation.json'} 與 {OUT / 'report.md'}")


if __name__ == "__main__":
    main()
