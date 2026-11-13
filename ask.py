"""Send one ad-hoc question to the agent and print every command it decides to run.

    uv run ask.py "這台機器的 hostname 是什麼？"

Useful for seeing that the commands are chosen by the model on the spot and
executed on the worker VM, not written in any program here.
"""

import sys

import anthropic

import reconcile


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit('usage: uv run ask.py "your question"')
    reconcile.TASK = sys.argv[1]
    reconcile.run_session(anthropic.Anthropic())


if __name__ == "__main__":
    main()
