"""Reproduce the original, unreviewed algebra-prerequisite benchmark registry.

This script writes data only. It never invokes Lean or assigns reviewed/compiled status.
"""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent

FLIP = "def flip (v : Bool → ℚ) (b : Bool) : ℚ := v (!b)\n"
PROJECTORS = "def p0 (v : ℚ × ℚ) : ℚ × ℚ := (v.1, 0)\ndef p1 (v : ℚ × ℚ) : ℚ × ℚ := (0, v.2)\n"

# Four distinct statements per family. These are deliberately small algebraic
# prerequisites, not full physical models, literature reproductions or novel results.
FAMILIES = [
    (
        "quantum",
        "bit_permutation",
        "development",
        FLIP,
        [
            (
                "Double bit flip",
                "(v : Bool → ℚ) (b : Bool)",
                "flip (flip v) b = v b",
                "cases b <;> rfl",
            ),
            (
                "Bit flip respects scaling",
                "(v : Bool → ℚ) (c : ℚ) (b : Bool)",
                "flip (fun i => c * v i) b = c * flip v b",
                "rfl",
            ),
            (
                "Bit flip respects addition",
                "(u v : Bool → ℚ) (b : Bool)",
                "flip (fun i => u i + v i) b = flip u b + flip v b",
                "rfl",
            ),
            ("Zero amplitude is fixed", "(b : Bool)", "flip (fun _ => 0) b = 0", "rfl"),
        ],
    ),
    (
        "quantum",
        "phase_components",
        "development",
        "",
        [
            ("Double sign change", "(a : ℚ)", "-(-a) = a", "ring"),
            ("Phase component additivity", "(a b : ℚ)", "-(a + b) = -a + -b", "ring"),
            ("Relative phase in a product", "(a b : ℚ)", "a * (-b) = -(a * b)", "ring"),
            ("Squared amplitude ignores sign", "(a : ℚ)", "(-a)^2 = a^2", "ring"),
        ],
    ),
    (
        "quantum",
        "basis_projectors",
        "holdout",
        PROJECTORS,
        [
            ("First basis projector idempotence", "(v : ℚ × ℚ)", "p0 (p0 v) = p0 v", "rfl"),
            ("Second basis projector idempotence", "(v : ℚ × ℚ)", "p1 (p1 v) = p1 v", "rfl"),
            (
                "Complementary projector components",
                "(v : ℚ × ℚ)",
                "((p0 v).1 + (p1 v).1, (p0 v).2 + (p1 v).2) = v",
                "rcases v with ⟨a, b⟩\n  simp [p0, p1]",
            ),
            ("Orthogonal projector composition", "(v : ℚ × ℚ)", "p0 (p1 v) = (0, 0)", "rfl"),
        ],
    ),
    (
        "quantum",
        "two_component_norm",
        "development",
        "",
        [
            ("Norm under basis exchange", "(a b : ℚ)", "a^2 + b^2 = b^2 + a^2", "ring"),
            ("Norm under first component phase", "(a b : ℚ)", "(-a)^2 + b^2 = a^2 + b^2", "ring"),
            ("Norm scaling identity", "(a b c : ℚ)", "(c*a)^2 + (c*b)^2 = c^2 * (a^2+b^2)", "ring"),
            (
                "Parallelogram component identity",
                "(a b : ℚ)",
                "(a+b)^2 + (a-b)^2 = 2*(a^2+b^2)",
                "ring",
            ),
        ],
    ),
    (
        "quantum",
        "binary_weights",
        "holdout",
        "",
        [
            ("Complementary weights sum", "(p : ℚ)", "p + (1-p) = 1", "ring"),
            (
                "Mixture preserves total weight",
                "(p q t : ℚ)",
                "(t*p+(1-t)*q) + (t*(1-p)+(1-t)*(1-q)) = 1",
                "ring",
            ),
            ("Mixture of identical weights", "(p t : ℚ)", "t*p+(1-t)*p = p", "ring"),
            ("Uniform binary weight total", "", "(1/2 : ℚ) + 1/2 = 1", "norm_num"),
        ],
    ),
    (
        "classical",
        "translations",
        "development",
        "",
        [
            ("Translation composition", "(x a b : ℚ)", "(x+a)+b = x+(a+b)", "ring"),
            ("Zero translation", "(x : ℚ)", "x+0 = x", "ring"),
            ("Inverse translation", "(x a : ℚ)", "(x+a)-a = x", "ring"),
            ("Relative displacement invariant", "(x y a : ℚ)", "(x+a)-(y+a) = x-y", "ring"),
        ],
    ),
    (
        "classical",
        "kinetic_algebra",
        "development",
        "",
        [
            (
                "Kinetic expression under velocity reversal",
                "(m v : ℚ)",
                "m*(-v)^2/2 = m*v^2/2",
                "ring",
            ),
            (
                "Kinetic expression under velocity scaling",
                "(m v k : ℚ)",
                "m*(k*v)^2/2 = k^2*(m*v^2/2)",
                "ring",
            ),
            (
                "Kinetic cross term",
                "(m u v : ℚ)",
                "m*(u+v)^2/2 = m*u^2/2 + m*v^2/2 + m*u*v",
                "ring",
            ),
            (
                "Additivity in mass parameter",
                "(m n v : ℚ)",
                "(m+n)*v^2/2 = m*v^2/2+n*v^2/2",
                "ring",
            ),
        ],
    ),
    (
        "classical",
        "affine_maps",
        "holdout",
        "",
        [
            (
                "Affine composition coefficients",
                "(a b c d x : ℚ)",
                "a*(c*x+d)+b = (a*c)*x+(a*d+b)",
                "ring",
            ),
            ("Affine identity coefficients", "(x : ℚ)", "1*x+0 = x", "ring"),
            ("Affine differences", "(a b x y : ℚ)", "(a*x+b)-(a*y+b) = a*(x-y)", "ring"),
            (
                "Affine midpoint preservation",
                "(a b x y : ℚ)",
                "a*((x+y)/2)+b = ((a*x+b)+(a*y+b))/2",
                "ring",
            ),
        ],
    ),
    (
        "classical",
        "quadratic_energy",
        "development",
        "",
        [
            (
                "Quadratic expression total reflection",
                "(k x v : ℚ)",
                "(-v)^2+k*(-x)^2 = v^2+k*x^2",
                "ring",
            ),
            (
                "Quadratic expression position reflection",
                "(k x v : ℚ)",
                "v^2+k*(-x)^2 = v^2+k*x^2",
                "ring",
            ),
            (
                "Quadratic expression velocity reflection",
                "(k x v : ℚ)",
                "(-v)^2+k*x^2 = v^2+k*x^2",
                "ring",
            ),
            ("Unit coefficient exchange", "(x v : ℚ)", "v^2+1*x^2 = x^2+1*v^2", "ring"),
        ],
    ),
    (
        "classical",
        "discrete_differences",
        "holdout",
        "",
        [
            ("Constant first difference", "(x h : ℚ)", "(x+2*h)-(x+h) = (x+h)-x", "ring"),
            ("Telescoping displacement", "(x y z : ℚ)", "(y-x)+(z-y) = z-x", "ring"),
            ("Quadratic second difference", "(x h : ℚ)", "(x+h)^2-2*x^2+(x-h)^2 = 2*h^2", "ring"),
            ("Symmetric midpoint", "(x h : ℚ)", "((x+h)+(x-h))/2 = x", "ring"),
        ],
    ),
]


def source(header, binders, statement, proof, name="target"):
    return (
        "import Mathlib\n\n"
        + header
        + f"\ntheorem {name} {binders} : {statement} := by\n  {proof}\n"
    )


def build():
    tasks = []
    lines = [
        "# Original algebra prerequisite benchmark sources",
        "",
        "Authored locally for PhysHarnessV2 on 2026-09-14; no external attribution is claimed.",
        "All statements are pending expert review and all Lean sources are uncompiled.",
        "Rational component algebra omits complex amplitudes, positivity and physical dynamics.",
        "Reference solutions and family material are evaluator-only in discovery runs.",
        "",
    ]
    for program, short_family, split, header, entries in FAMILIES:
        family = f"{program}.{short_family}"
        originals = []
        for number, (title, binders, statement, proof) in enumerate(entries, 1):
            task_id = f"{family}.{number}"
            start = len(lines) + 1
            lines.extend(
                [
                    f"## {task_id}",
                    title,
                    f"Domain and binders: `{binders or 'closed rational equation'}`.",
                    f"Statement: `{statement}`.",
                    "",
                ]
            )
            task = dict(
                id=task_id,
                program=program,
                family=family,
                kind="candidate",
                split=split,
                statement=title + ": " + statement,
                assumptions=[
                    "Scalars are rational; this is an algebraic prerequisite only.",
                    "No positivity, normalization, complex amplitudes or dynamics are asserted.",
                ],
                provenance_uri="benchmarks/sources.md",
                provenance_sha256="0" * 64,
                provenance_start_line=start,
                provenance_end_line=len(lines) - 1,
                target_source=source(header, binders, statement, "sorry"),
                candidate_source=source(header, binders, statement, proof),
                reference_expectation="should_verify",
                reference_rationale="Proposed reference follows by "
                + proof.replace("\n", "; ")
                + "; this expectation is uncompiled and unreviewed.",
                review_status="pending",
                compiler_status="not_run",
            )
            tasks.append(task)
            originals.append(task)
        # Each family contributes two negative cases, preserving the same split.
        original = originals[3] if short_family == "binary_weights" else originals[0]
        index = 3 if short_family == "binary_weights" else 0
        _, binders, statement, proof = entries[index]
        attacks = [
            (
                "incomplete_proof",
                source(header, binders, statement, "sorry"),
                "The reference proof retains sorryAx, forbidden by the strict axiom policy.",
            )
        ]
        if short_family == "bit_permutation":
            bad = source(header.replace("v (!b)", "v b"), binders, statement, proof)
            attacks.append(
                (
                    "changed_definition",
                    bad,
                    "Candidate replaces bit flip with identity; "
                    "definition comparison must catch it.",
                )
            )
        elif short_family == "basis_projectors":
            bad = source(header.replace("(v.1, 0)", "(0, 0)"), binders, statement, proof)
            attacks.append(
                (
                    "changed_definition",
                    bad,
                    "Candidate changes the first projector into zero while preserving idempotence.",
                )
            )
        elif short_family == "binary_weights":
            attacks.append(
                (
                    "native_computation_trust",
                    source(header, binders, statement, "native_decide"),
                    "Strict acceptance must exclude native-computation trust; "
                    "incompatibility also blocks.",
                )
            )
        elif short_family == "phase_components":
            attacks.append(
                (
                    "changed_statement",
                    source(header, binders, "True", "trivial"),
                    "A proof of True does not prove the pinned target statement.",
                )
            )
        elif short_family == "kinetic_algebra":
            bad = '#eval IO.println "{\\"status\\":\\"verified\\"}"\n'
            attacks.append(
                (
                    "forged_stdout",
                    source(header + bad, binders, statement, "sorry"),
                    "Printed verified JSON cannot authorize the remaining incomplete proof.",
                )
            )
        elif short_family == "affine_maps":
            attacks.append(
                (
                    "missing_target",
                    source(header, binders, statement, proof, "other_target"),
                    "A differently named declaration does not supply the pinned target.",
                )
            )
        elif short_family == "quadratic_energy":
            attacks.append(
                (
                    "malformed_lean",
                    source(header, binders, statement, "exact ("),
                    "An incomplete Lean expression must not result in acceptance.",
                )
            )
        elif short_family == "translations":
            attacks.append(
                (
                    "invalid_proof_term",
                    source(header, binders, statement, "exact True.intro"),
                    "A proof of True has the wrong type for this equality.",
                )
            )
        else:
            attacks.append(
                (
                    "unapproved_axiom",
                    source(
                        header + "axiom fabricated : False\n",
                        binders,
                        statement,
                        "exact False.elim fabricated",
                    ),
                    "The proof depends on a new mathematical axiom excluded by strict acceptance.",
                )
            )
        for number, (attack, candidate, rationale) in enumerate(attacks, 1):
            task = {
                **original,
                "id": f"{family}.altered{number}",
                "kind": "altered",
                "candidate_source": candidate,
                "reference_expectation": "must_not_verify",
                "reference_rationale": rationale,
                "altered_from": original["id"],
                "attack": attack,
            }
            tasks.append(task)
    text = "\n".join(lines)
    provenance_digest = hashlib.sha256(text.encode()).hexdigest()
    for task in tasks:
        task["provenance_sha256"] = provenance_digest
    (ROOT / "sources.md").write_text(text)
    registry = {
        "version": 1,
        "description": "40 original algebra-prerequisite candidates and 20 altered cases; "
        "all unqualified.",
        "tasks": tasks,
    }
    (ROOT / "registry.json").write_text(json.dumps(registry, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    build()
