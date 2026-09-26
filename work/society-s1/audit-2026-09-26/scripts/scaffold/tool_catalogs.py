"""Build the society tool catalogs offline (test fixtures, no service, no network) and
measure each tool definition's JSON size. Writes out/tool_catalogs.json.
Run from <repo>: PYTHONPATH=src:tests .venv/bin/python <this>"""
import json, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
import test_society_tools as T  # noqa: E402

def measure(dispatcher):
    defs = dispatcher.definitions
    per = {d["name"]: {"chars": len(json.dumps(d, ensure_ascii=False, separators=(",", ":"))),
                       "desc_chars": len(d.get("description") or ""),
                       "props": len(d["parameters"]["properties"])} for d in defs}
    return {"count": len(defs), "chars": len(json.dumps(defs, ensure_ascii=False, separators=(",", ":"))),
            "tools": per}

out = {
    "root": measure(T.catalog({"reply_to_parent_task_id": None})),
    "recruit_joined": measure(T.catalog({"reply_to_parent_task_id": "parent"})),
    "referee_informal": measure(T.referee_catalog("informal")),
    "referee_fidelity": measure(T.referee_catalog("fidelity")),
}
(HERE / "out" / "tool_catalogs.json").write_text(json.dumps(out, indent=1))
for k, v in out.items():
    print(k, v["count"], v["chars"])
    for n, t in sorted(v["tools"].items(), key=lambda kv: -kv[1]["chars"]):
        print(f"   {n:26s} {t['chars']:6d} desc={t['desc_chars']:5d} props={t['props']}")
