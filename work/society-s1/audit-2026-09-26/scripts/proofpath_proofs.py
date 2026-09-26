"""Proof-path audit: write out/proofs/<arm>.lean, the verified candidate of each arm
(verification record `candidate_sha256`, read sha256-checked from the arm export).
Usage: python proofpath_proofs.py ARM [ARM ...]"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path[:0] = [HERE, os.path.dirname(HERE)]  # extract.py: next to this file, or one level up (as-run)
import extract as X  # noqa: E402

OUT = os.environ.get("PROOFS_OUT") or os.path.join(HERE, "out", "proofs")

if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    for arm in sys.argv[1:]:
        a = X.Arm(arm)
        shas = {p["candidate_sha256"] for _, p in a.records("verification") if p.get("candidate_sha256")}
        if len(shas) != 1:
            sys.exit(f"{arm}: expected one verified candidate, found {len(shas)}")
        (sha,) = shas
        with open(os.path.join(OUT, f"{arm}.lean"), "wb") as fh:
            fh.write(a.content(sha))
        print(arm, sha[:12])
