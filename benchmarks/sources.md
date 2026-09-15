# Original algebra prerequisite benchmark sources

Authored locally for PhysHarnessV2 on 2026-09-14; no external attribution is claimed.
All statements are pending expert review and all Lean sources are uncompiled.
Rational component algebra omits complex amplitudes, positivity and physical dynamics.
Reference solutions and family material are evaluator-only in discovery runs.

## quantum.bit_permutation.1
Double bit flip
Domain and binders: `(v : Bool → ℚ) (b : Bool)`.
Statement: `flip (flip v) b = v b`.

## quantum.bit_permutation.2
Bit flip respects scaling
Domain and binders: `(v : Bool → ℚ) (c : ℚ) (b : Bool)`.
Statement: `flip (fun i => c * v i) b = c * flip v b`.

## quantum.bit_permutation.3
Bit flip respects addition
Domain and binders: `(u v : Bool → ℚ) (b : Bool)`.
Statement: `flip (fun i => u i + v i) b = flip u b + flip v b`.

## quantum.bit_permutation.4
Zero amplitude is fixed
Domain and binders: `(b : Bool)`.
Statement: `flip (fun _ => 0) b = 0`.

## quantum.phase_components.1
Double sign change
Domain and binders: `(a : ℚ)`.
Statement: `-(-a) = a`.

## quantum.phase_components.2
Phase component additivity
Domain and binders: `(a b : ℚ)`.
Statement: `-(a + b) = -a + -b`.

## quantum.phase_components.3
Relative phase in a product
Domain and binders: `(a b : ℚ)`.
Statement: `a * (-b) = -(a * b)`.

## quantum.phase_components.4
Squared amplitude ignores sign
Domain and binders: `(a : ℚ)`.
Statement: `(-a)^2 = a^2`.

## quantum.basis_projectors.1
First basis projector idempotence
Domain and binders: `(v : ℚ × ℚ)`.
Statement: `p0 (p0 v) = p0 v`.

## quantum.basis_projectors.2
Second basis projector idempotence
Domain and binders: `(v : ℚ × ℚ)`.
Statement: `p1 (p1 v) = p1 v`.

## quantum.basis_projectors.3
Complementary projector components
Domain and binders: `(v : ℚ × ℚ)`.
Statement: `((p0 v).1 + (p1 v).1, (p0 v).2 + (p1 v).2) = v`.

## quantum.basis_projectors.4
Orthogonal projector composition
Domain and binders: `(v : ℚ × ℚ)`.
Statement: `p0 (p1 v) = (0, 0)`.

## quantum.two_component_norm.1
Norm under basis exchange
Domain and binders: `(a b : ℚ)`.
Statement: `a^2 + b^2 = b^2 + a^2`.

## quantum.two_component_norm.2
Norm under first component phase
Domain and binders: `(a b : ℚ)`.
Statement: `(-a)^2 + b^2 = a^2 + b^2`.

## quantum.two_component_norm.3
Norm scaling identity
Domain and binders: `(a b c : ℚ)`.
Statement: `(c*a)^2 + (c*b)^2 = c^2 * (a^2+b^2)`.

## quantum.two_component_norm.4
Parallelogram component identity
Domain and binders: `(a b : ℚ)`.
Statement: `(a+b)^2 + (a-b)^2 = 2*(a^2+b^2)`.

## quantum.binary_weights.1
Complementary weights sum
Domain and binders: `(p : ℚ)`.
Statement: `p + (1-p) = 1`.

## quantum.binary_weights.2
Mixture preserves total weight
Domain and binders: `(p q t : ℚ)`.
Statement: `(t*p+(1-t)*q) + (t*(1-p)+(1-t)*(1-q)) = 1`.

## quantum.binary_weights.3
Mixture of identical weights
Domain and binders: `(p t : ℚ)`.
Statement: `t*p+(1-t)*p = p`.

## quantum.binary_weights.4
Uniform binary weight total
Domain and binders: `closed rational equation`.
Statement: `(1/2 : ℚ) + 1/2 = 1`.

## classical.translations.1
Translation composition
Domain and binders: `(x a b : ℚ)`.
Statement: `(x+a)+b = x+(a+b)`.

## classical.translations.2
Zero translation
Domain and binders: `(x : ℚ)`.
Statement: `x+0 = x`.

## classical.translations.3
Inverse translation
Domain and binders: `(x a : ℚ)`.
Statement: `(x+a)-a = x`.

## classical.translations.4
Relative displacement invariant
Domain and binders: `(x y a : ℚ)`.
Statement: `(x+a)-(y+a) = x-y`.

## classical.kinetic_algebra.1
Kinetic expression under velocity reversal
Domain and binders: `(m v : ℚ)`.
Statement: `m*(-v)^2/2 = m*v^2/2`.

## classical.kinetic_algebra.2
Kinetic expression under velocity scaling
Domain and binders: `(m v k : ℚ)`.
Statement: `m*(k*v)^2/2 = k^2*(m*v^2/2)`.

## classical.kinetic_algebra.3
Kinetic cross term
Domain and binders: `(m u v : ℚ)`.
Statement: `m*(u+v)^2/2 = m*u^2/2 + m*v^2/2 + m*u*v`.

## classical.kinetic_algebra.4
Additivity in mass parameter
Domain and binders: `(m n v : ℚ)`.
Statement: `(m+n)*v^2/2 = m*v^2/2+n*v^2/2`.

## classical.affine_maps.1
Affine composition coefficients
Domain and binders: `(a b c d x : ℚ)`.
Statement: `a*(c*x+d)+b = (a*c)*x+(a*d+b)`.

## classical.affine_maps.2
Affine identity coefficients
Domain and binders: `(x : ℚ)`.
Statement: `1*x+0 = x`.

## classical.affine_maps.3
Affine differences
Domain and binders: `(a b x y : ℚ)`.
Statement: `(a*x+b)-(a*y+b) = a*(x-y)`.

## classical.affine_maps.4
Affine midpoint preservation
Domain and binders: `(a b x y : ℚ)`.
Statement: `a*((x+y)/2)+b = ((a*x+b)+(a*y+b))/2`.

## classical.quadratic_energy.1
Quadratic expression total reflection
Domain and binders: `(k x v : ℚ)`.
Statement: `(-v)^2+k*(-x)^2 = v^2+k*x^2`.

## classical.quadratic_energy.2
Quadratic expression position reflection
Domain and binders: `(k x v : ℚ)`.
Statement: `v^2+k*(-x)^2 = v^2+k*x^2`.

## classical.quadratic_energy.3
Quadratic expression velocity reflection
Domain and binders: `(k x v : ℚ)`.
Statement: `(-v)^2+k*x^2 = v^2+k*x^2`.

## classical.quadratic_energy.4
Unit coefficient exchange
Domain and binders: `(x v : ℚ)`.
Statement: `v^2+1*x^2 = x^2+1*v^2`.

## classical.discrete_differences.1
Constant first difference
Domain and binders: `(x h : ℚ)`.
Statement: `(x+2*h)-(x+h) = (x+h)-x`.

## classical.discrete_differences.2
Telescoping displacement
Domain and binders: `(x y z : ℚ)`.
Statement: `(y-x)+(z-y) = z-x`.

## classical.discrete_differences.3
Quadratic second difference
Domain and binders: `(x h : ℚ)`.
Statement: `(x+h)^2-2*x^2+(x-h)^2 = 2*h^2`.

## classical.discrete_differences.4
Symmetric midpoint
Domain and binders: `(x h : ℚ)`.
Statement: `((x+h)+(x-h))/2 = x`.
