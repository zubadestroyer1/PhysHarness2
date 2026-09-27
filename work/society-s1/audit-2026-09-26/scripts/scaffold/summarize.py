"""Summarize composition.json: input-token rent shares by category, per arm and hat, plus
turn-1 fixed context. Usage: summarize.py [--by-hat]"""
import json, sys, collections
from pathlib import Path
HERE = Path(__file__).resolve().parent
d = json.loads((HERE / "out" / "composition.json").read_text())
GROUP = {
    "tools_defs": "F_tools", "p_constitution": "F_constitution",
    "p_target": "F_problem", "p_objective": "F_problem",
    "p_target_dup": "F_bookkeeping", "p_target_review": "F_bookkeeping", "p_brief_task_record": "F_bookkeeping",
    "p_brief_indices": "F_bookkeeping", "p_brief_misc": "F_bookkeeping", "p_misc": "F_bookkeeping",
    "p_brief_state": "F_brief_state", "p_continuation": "F_continuation",
    "p_commons_view": "F_commons_view", "p_workforce": "F_workforce",
    "inj_peer_updates": "I_peer_updates", "inj_checkin_note": "I_checkin", "inj_anchor": "I_anchor", "inj_other": "I_other",
    "agent_args_work": "A_args_work", "agent_args_coord": "A_args_coord", "agent_args_other": "A_args_other", "agent_text": "A_text",
    "out_work": "O_work", "out_coord": "O_coord", "out_other": "O_other",
    "residual": "R_reasoning_residual",
}
def main():
  by_hat = "--by-hat" in sys.argv
  agg = collections.defaultdict(collections.Counter)
  tot = collections.Counter()
  for arm, sessions in d.items():
      for s in sessions:
          key = (arm, s["hat"]) if by_hat else (arm,)
          for t in s["turns"]:
              for k, v in t["parts"].items():
                  agg[key][GROUP.get(k, k)] += v
              agg[key]["_input"] += t["input"]; agg[key]["_turns"] += 1
  cols = ["F_tools", "F_constitution", "F_problem", "F_bookkeeping", "F_brief_state", "F_continuation",
          "F_commons_view", "F_workforce", "I_peer_updates", "I_checkin", "I_anchor", "A_args_work", "A_args_coord", "A_text",
          "O_work", "O_coord", "O_other", "R_reasoning_residual"]
  print("key".ljust(34), "turns  inputM ", " ".join(c.split("_", 1)[1][:9].rjust(9) for c in cols))
  for key, c in sorted(agg.items()):
      inp = c["_input"]
      print(" ".join(key).ljust(34), f"{c['_turns']:5d} {inp/1e6:7.2f} ", " ".join(f"{100*c[col]/inp:8.1f}%" for col in cols))

if __name__ == "__main__":
  main()
