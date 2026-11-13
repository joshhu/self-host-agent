"""Review console for the invoice-reconciliation agent.

    uv run uvicorn app:app --port 8300

The browser never talks to Anthropic or to the worker VM. This backend does:
it starts the session, relays what the agent is doing, keeps the result, and
records the reviewer's decisions. It listens on localhost only.
"""

import json
import threading
import time
from pathlib import Path

import anthropic
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

import reconcile

ROOT = Path(__file__).parent
OUT = ROOT / "out"
RESULT = OUT / "reconciliation.json"
DECISIONS = OUT / "decisions.json"

app = FastAPI()
lock = threading.Lock()
run = {"running": False, "started": None, "finished": None, "log": [], "error": None}


def describe(event) -> str | None:
    """Turn one agent event into a line a finance clerk can follow."""
    if event.type == "agent.tool_use":
        text = event.input.get("command") or event.input.get("file_path") or ""
        if "sqlite3" in text:
            return "查詢 ERP 資料庫"
        if "/srv/ap/inbox" in text:
            return "讀取發票"
        if event.name == "write":
            return f"寫入 {Path(text).name}"
        if event.name == "bash" and "python" in text:
            return "執行比對程式"
        return {"read": "讀取檔案", "bash": "執行指令"}.get(event.name, event.name)
    if event.type == "agent.message":
        return "整理結果"
    if event.type == "session.error":
        return f"發生錯誤：{event.error}"
    return None


def worker() -> None:
    def on_event(event):
        line = describe(event)
        if line:
            run["log"].append({"t": round(time.time() - run["started"]), "text": line})

    try:
        run["log"].append({"t": 0, "text": "已交辦給 agent，等待 worker 接手"})
        reconcile.run_session(anthropic.Anthropic(), on_event)
        run["log"].append({"t": round(time.time() - run["started"]), "text": "取回對帳結果"})
        json.loads(reconcile.fetch("reconciliation.json"))  # fails loudly if the agent wrote bad JSON
        reconcile.fetch("report.md")
        DECISIONS.write_text("{}")
    except Exception as exc:  # shown to the reviewer; the page stays usable with the previous result
        run["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        run["finished"] = time.time()
        run["running"] = False


def read_json(path: Path, default):
    return json.loads(path.read_text()) if path.exists() else default


@app.get("/")
def index():
    return FileResponse(ROOT / "web" / "index.html")


@app.get("/api/state")
def state():
    return {
        "running": run["running"],
        "elapsed": round((run["finished"] or time.time()) - run["started"]) if run["started"] else None,
        "log": run["log"],
        "error": run["error"],
        "invoices": read_json(RESULT, {"invoices": []})["invoices"],
        "decisions": read_json(DECISIONS, {}),
    }


@app.post("/api/run", status_code=202)
def start_run():
    with lock:
        if run["running"]:
            raise HTTPException(409, "對帳正在進行中")
        run.update(running=True, started=time.time(), finished=None, log=[], error=None)
    threading.Thread(target=worker, daemon=True).start()
    return {"started": True}


class Decision(BaseModel):
    files: list[str]
    decision: str | None  # "paid", "returned", or None to undo


@app.post("/api/decision")
def decide(body: Decision):
    if body.decision not in ("paid", "returned", None):
        raise HTTPException(422, "decision 必須是 paid、returned 或 null")
    known = {i["file"] for i in read_json(RESULT, {"invoices": []})["invoices"]}
    unknown = [f for f in body.files if f not in known]
    if unknown:
        raise HTTPException(404, f"找不到發票：{unknown}")
    with lock:
        decisions = read_json(DECISIONS, {})
        for file in body.files:
            if body.decision is None:
                decisions.pop(file, None)
            else:
                decisions[file] = body.decision
        OUT.mkdir(exist_ok=True)
        DECISIONS.write_text(json.dumps(decisions, ensure_ascii=False, indent=2))
    return decisions
