"""Compare the agent's result (out/reconciliation.json) with the answer key (out/expected.json).

    uv run verify.py

An invoice counts as correct when the decision matches and, for an exception,
the expected reason code is among the reasons the agent gave.
"""

import json
import sys
from pathlib import Path

OUT = Path(__file__).parent / "out"


def main() -> int:
    expected = {e["file"]: e for e in json.loads((OUT / "expected.json").read_text())}
    actual = {a["file"]: a for a in json.loads((OUT / "reconciliation.json").read_text())["invoices"]}

    wrong = 0
    for file, exp in expected.items():
        got = actual.get(file)
        if got is None:
            problem = "agent 沒有處理這張發票"
        elif got["decision"] != exp["decision"]:
            problem = f"應為 {exp['decision']}，agent 判為 {got['decision']} {got['reasons']}"
        elif exp["reason"] and exp["reason"] not in got["reasons"]:
            problem = f"應含 {exp['reason']}，agent 給的是 {got['reasons']}"
        elif got["total"] != exp["total"]:
            problem = f"總額應為 {exp['total']}，agent 讀到 {got['total']}"
        else:
            problem = ""
        wrong += bool(problem)
        label = exp["reason"] or "approve"
        print(f"{'錯' if problem else '對'}  {file:<10} {label:<20} {problem or exp['note']}")

    extra = sorted(set(actual) - set(expected))
    if extra:
        wrong += len(extra)
        print(f"agent 多列了不存在的檔案：{extra}")
    print(f"\n{len(expected) - wrong}/{len(expected)} 張判斷正確")
    return 1 if wrong else 0


if __name__ == "__main__":
    sys.exit(main())
