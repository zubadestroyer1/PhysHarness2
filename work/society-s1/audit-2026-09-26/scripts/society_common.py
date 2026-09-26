"""Shared read-only loaders for the society audit (S1 live runs)."""
import collections
import json
import os
import sqlite3
import sys
from datetime import datetime

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
sys.path.insert(0, os.path.join(REPO, "src"))
ARMS = os.path.join(REPO, ".state", "s1", "arms")
PRICE_IN = 2.50e-6
PRICE_OUT = 10.0e-6


def ts(value):
    return datetime.fromisoformat(value).timestamp()


def connect(arm):
    return sqlite3.connect(f"file:{ARMS}/{arm}/harness.db?mode=ro", uri=True)


def export_dir(arm):
    base = os.path.join(ARMS, arm, "exports")
    if not os.path.isdir(base):
        return None
    stamps = sorted(os.listdir(base))
    return os.path.join(base, stamps[-1]) if stamps else None


def read_blob(arm, sha256):
    d = export_dir(arm)
    if d:
        p = os.path.join(d, sha256)
        if os.path.exists(p):
            return open(p, "rb").read()
    p = os.path.join(ARMS, arm, "artifacts", sha256[:2], sha256)
    if os.path.exists(p):
        return open(p, "rb").read()
    return None


class Arm:
    def __init__(self, name):
        self.name = name
        self.c = connect(name)
        self.records = collections.defaultdict(dict)
        for rid, kind, payload in self.c.execute(
            "select id, kind, payload from records where kind != 'artifact'"
        ):
            self.records[kind][rid] = json.loads(payload)
        self.events = [
            dict(sequence=s, kind=k, aggregate_id=a, operation_id=o, payload=json.loads(p), t=ts(c))
            for s, k, a, o, p, c in self.c.execute(
                "select sequence, kind, aggregate_id, operation_id, payload, created_at from events "
                "where kind != 'artifact.created' order by sequence"
            )
        ]
        self.by_kind = collections.defaultdict(list)
        for e in self.events:
            self.by_kind[e["kind"]].append(e)
        exps = list(self.records["experiment"].values())
        self.experiment = exps[0] if exps else None
        self.t0 = ts(self.experiment["created_at"]) if self.experiment else None

    def artifacts(self, kind=None):
        q = "select payload from records where kind='artifact'"
        args = ()
        if kind:
            q += " and json_extract(payload,'$.artifact_kind')=?"
            args = (kind,)
        for (p,) in self.c.execute(q, args):
            yield json.loads(p)

    def reservation_costs(self):
        """actual cost per task_id, from resources.settled joined to model_reservation."""
        cols = [r[0] for r in self.c.execute("select id, actual from reservations")]
        settled = {rid: (actual or 0) / 1e6
                   for rid, actual in self.c.execute("select id, actual from reservations")}
        per_task = collections.Counter()
        for r in self.records["model_reservation"].values():
            per_task[r["task_id"]] += settled.get(r["reservation_id"], 0.0)
        return per_task

    def runtime_events(self):
        out = []
        for a in self.artifacts("runtime_event"):
            raw = read_blob(self.name, a["sha256"])
            if raw is None:
                continue
            e = json.loads(raw)
            e["t"] = ts(a["created_at"])
            e["task_id"] = (a.get("provenance") or {}).get("task_id")
            e["branch_id"] = a.get("branch_id")
            out.append(e)
        out.sort(key=lambda e: e["t"])
        return out

    def rel(self, t):
        return t - self.t0


def decode_checkpoint(arm, manifest_payload):
    from physharness.execution.checkpoint_chunks import decode
    raw = read_blob(arm, manifest_payload["sha256"])

    def read(ref):
        return read_blob(arm, ref["sha256"])

    return decode(raw, read)
