"""Deterministic stand-in for the Lean REPL (leanprover-community/repl) used by tests.

It speaks the real framing: one JSON command per blank-line-separated block on stdin and
one pretty-printed JSON response followed by a blank line on stdout.

Commands:
- ``{"cmd"}`` without ``env`` starts a fresh environment (import lines are accepted silently);
  ``{"cmd", "env"}`` continues an existing one. In both, each line containing ``sorry``
  yields a ``sorries`` entry with a new proofState (``-- goal: G`` on that line sets the
  goal to ``⊢ G``). ``ERROR`` yields an error message, ``WARN`` a warning carrying the line
  text, and ``#print axioms N`` an info message. The body ``CRASH`` exits the process; the
  body ``SLEEP`` hangs.
- ``{"tactic", "proofState"}``: ``linarith`` closes proofState 0, ``exact?`` closes proofState 1
  with a "Try this" suggestion, and ``extract_goal`` reports
  ``theorem extracted_1 (x : Nat) : x = x := sorry`` unless the goal mentions NOEXTRACT.

When ``FAKE_LEAN_REPL_DIR`` is set, the process appends its pid to ``pids.txt`` and every
received command to ``commands.jsonl`` there.
"""

import json
import os
import sys
import time

LOG_DIR = os.environ.get("FAKE_LEAN_REPL_DIR")
DEFAULT_GOAL = "x : Nat\n⊢ x = x"


def record(name, text):
    if LOG_DIR:
        with open(os.path.join(LOG_DIR, name), "a", encoding="utf-8") as stream:
            stream.write(text + "\n")


def message(severity, line, column, data):
    return {
        "severity": severity,
        "pos": {"line": line, "column": column},
        "endPos": None,
        "data": data,
    }


class FakeRepl:
    def __init__(self):
        self.envs = 0
        self.goals = {}

    def state(self, goal):
        number = len(self.goals)
        self.goals[number] = goal
        return number

    def command(self, request):
        if "env" in request and not (
            isinstance(request["env"], int) and 0 <= request["env"] < self.envs
        ):
            return {"message": "Unknown environment."}
        text = request["cmd"]
        if text.strip() == "CRASH":
            sys.exit(3)
        if text.strip() == "SLEEP":
            time.sleep(3600)
        messages, sorries = [], []
        for number, line in enumerate(text.split("\n"), 1):
            column = line.find("sorry")
            if column >= 0:
                goal = DEFAULT_GOAL
                if "-- goal:" in line:
                    goal = "⊢ " + line.split("-- goal:", 1)[1].strip()
                sorries.append(
                    {
                        "pos": {"line": number, "column": column},
                        "endPos": {"line": number, "column": column + 5},
                        "goal": goal,
                        "proofState": self.state(goal),
                    }
                )
            if "ERROR" in line:
                messages.append(
                    message("error", number, line.find("ERROR"), "unknown identifier 'ERROR'")
                )
            if "WARN" in line:
                messages.append(message("warning", number, 0, line))
            if line.startswith("#print axioms "):
                name = line.split()[2]
                messages.append(
                    message(
                        "info",
                        number,
                        0,
                        f"'{name}' depends on axioms: [propext,\n Classical.choice,\n Quot.sound]",
                    )
                )
        if sorries:
            messages.insert(0, message("warning", 1, 0, "declaration uses `sorry`"))
        self.envs += 1
        response = {"env": self.envs - 1}
        if messages:
            response["messages"] = messages
        if sorries:
            response["sorries"] = sorries
        return response

    def tactic(self, request):
        number, tactic = request.get("proofState"), request.get("tactic")
        if number not in self.goals:
            return {"message": "Unknown proof state."}
        goal = self.goals[number]
        if tactic == "linarith" and number == 0:
            return {"proofStatus": "Completed", "proofState": self.state(None), "goals": []}
        if tactic == "exact?" and number == 1:
            return {
                "proofStatus": "Completed",
                "proofState": self.state(None),
                "goals": [],
                "messages": [message("info", 0, 0, "Try this:\n  [apply] exact fake_lemma")],
            }
        if tactic == "extract_goal":
            if "NOEXTRACT" in (goal or ""):
                return {"message": "Lean error:\nextract_goal failed"}
            return {
                "proofStatus": "Incomplete: open goals remain",
                "proofState": self.state(goal),
                "goals": [goal],
                "messages": [
                    message("info", 0, 0, "theorem extracted_1 (x : Nat) : x = x := sorry")
                ],
            }
        if tactic == "omega":
            return {"message": "Lean error:\nomega could not prove the goal"}
        if tactic in ("norm_num", "simp"):
            return {
                "proofState": self.state(goal),
                "goals": [goal],
                "messages": [message("error", 0, 0, tactic + " failed")],
            }
        return {
            "proofStatus": "Incomplete: open goals remain",
            "proofState": self.state(goal),
            "goals": [goal],
        }


def main():
    record("pids.txt", str(os.getpid()))
    repl, block = FakeRepl(), []
    while True:
        line = sys.stdin.buffer.readline()
        if not line:
            return
        if line.strip():
            block.append(line.decode("utf-8"))
            continue
        if not block:
            continue
        request, block = json.loads("".join(block)), []
        record("commands.jsonl", json.dumps(request, ensure_ascii=False))
        response = repl.tactic(request) if "tactic" in request else repl.command(request)
        output = json.dumps(response, indent=1, ensure_ascii=False) + "\n\n"
        sys.stdout.buffer.write(output.encode("utf-8"))
        sys.stdout.buffer.flush()


if __name__ == "__main__":
    main()
