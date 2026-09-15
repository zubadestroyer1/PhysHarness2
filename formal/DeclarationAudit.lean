/- Trusted environment audit. Execute only inside the Linux physics builder.
   Printed axiom closures do not approve physical modeling or qualify containment. -/
import Physlib.ClassicalMechanics.HarmonicOscillator.Basic
import QuantumInfo.States.Pure.Qubit
import QuantumInfo.States.Mixed.MState

#check ClassicalMechanics.hamiltonEqOp
#print axioms ClassicalMechanics.hamiltonEqOp
#check ClassicalMechanics.hamiltonEqOp_eq_zero_iff_hamiltons_equations
#print axioms ClassicalMechanics.hamiltonEqOp_eq_zero_iff_hamiltons_equations
#check ClassicalMechanics.hamiltons_equations_varGradient
#print axioms ClassicalMechanics.hamiltons_equations_varGradient
#check ClassicalMechanics.HarmonicOscillator
#print axioms ClassicalMechanics.HarmonicOscillator
#check ClassicalMechanics.HarmonicOscillator.kineticEnergy
#print axioms ClassicalMechanics.HarmonicOscillator.kineticEnergy
#check ClassicalMechanics.HarmonicOscillator.potentialEnergy
#print axioms ClassicalMechanics.HarmonicOscillator.potentialEnergy
#check ClassicalMechanics.HarmonicOscillator.energy
#print axioms ClassicalMechanics.HarmonicOscillator.energy
#check ClassicalMechanics.HarmonicOscillator.EquationOfMotion
#print axioms ClassicalMechanics.HarmonicOscillator.EquationOfMotion
#check ClassicalMechanics.HarmonicOscillator.energy_conservation_of_equationOfMotion
#print axioms ClassicalMechanics.HarmonicOscillator.energy_conservation_of_equationOfMotion
#check ClassicalMechanics.HarmonicOscillator.hamiltonian
#print axioms ClassicalMechanics.HarmonicOscillator.hamiltonian
#check Qubit
#print axioms Qubit
#check Qubit.X
#print axioms Qubit.X
#check Qubit.X_sq
#print axioms Qubit.X_sq
#check Qubit.H
#print axioms Qubit.H
#check Qubit.H_sq
#print axioms Qubit.H_sq
#check Qubit.CNOT
#print axioms Qubit.CNOT
#check Qubit.controllize_mul
#print axioms Qubit.controllize_mul
#check MState
#print axioms MState
#check MState.pure
#print axioms MState.pure
#check MState.purity
#print axioms MState.purity
#check MState.traceLeft
#print axioms MState.traceLeft
#check MState.traceRight
#print axioms MState.traceRight
#check MState.traceLeft_prod_eq
#print axioms MState.traceLeft_prod_eq
#check MState.pure_iff_purity_one
#print axioms MState.pure_iff_purity_one
#check MState.purify_spec
#print axioms MState.purify_spec
#check Matrix.PosSemidef
#print axioms Matrix.PosSemidef
#check Matrix.PosDef
#print axioms Matrix.PosDef
