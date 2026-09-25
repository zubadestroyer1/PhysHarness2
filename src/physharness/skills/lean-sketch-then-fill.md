---
name: lean-sketch-then-fill
summary: Formalize an informal proof by compiling a Lean skeleton with sorry holes, turning holes into lemma nodes, and filling them easiest first.
applies_when: You have an informal proof to formalize, a monolithic Lean attempt keeps failing, or pieces of a proof could be filled by collaborators.
---
# Lean sketch-then-fill workflow

## When it applies
- An informal proof exists and needs a Lean proof.
- A direct attempt keeps failing, or the proof splits into pieces others could take.

## Core steps
1. Pin the statement. Check with lean_check that it elaborates, and that it says what
   the target means: types, quantifiers, ℕ/ℤ/ℝ coercions, division conventions.
2. Write a skeleton that mirrors the informal proof: a sequence of `have` steps, each
   closed by `sorry`, and a final step that uses them.
3. Run lean_sketch. It confirms that the skeleton type-checks and turns each hole's goal
   into a lemma node linked to the parent.
4. Fill the easiest holes first. Try automation (`simp`, `norm_num`, `ring`, `field_simp`,
   `positivity`, `linarith`, `nlinarith`), then `exact?` and `apply?`, then library
   search (search_library, read_source), then a focused manual proof.
5. If a hole is false or too hard, change the skeleton (strengthen a hypothesis or
   change an intermediate claim) instead of forcing it. Post the failure on the node.
6. Recompose: replace each `sorry` with its lemma, check the whole file with lean_check,
   and then use submit_for_verification.

## Pitfalls
- A skeleton that type-checks can still contain false holes. Test each hole's claim
  before investing in it.
- Hidden conventions: `n / 2` in ℕ truncates, `x⁻¹ = 0` at `x = 0`, `Real.sqrt` of a
  negative number is 0, and `Real.log 0 = 0`.
- A hole's goal carries its whole local context. Trim or generalize the hypotheses so
  the extracted lemma is reusable.
- Choose distinctive lemma names to avoid clashing with Mathlib.
- A local compile is evidence, not acceptance. Only the independent verifier accepts a
  proof. `#print axioms` must not list `sorryAx`.

## In Lean/Mathlib
- Skeleton idioms: `have h1 : claim := by sorry`, `suffices h : claim by ...`, `calc`
  chains whose steps are `by sorry`, `refine ⟨?_, ?_⟩` for conjunctions and
  existentials, and `obtain ⟨x, hx⟩ := h` to destructure.
- Search tactics `exact?`, `apply?`, `rw?` and `simp?` report the lemma they used; read
  it with read_source before relying on it.
- Keep each hole self-contained so it can become a standalone `lemma`.

## Numerical sanity check
- Evaluate each hole's claim on random and extreme inputs in Python before proving
  it. A counterexample saves hours; post it on the node.
