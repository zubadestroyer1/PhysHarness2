import QuantumInfo.States.Pure.Qubit

theorem library_target : Qubit.X * Qubit.X = 1 := by
  exact Qubit.X_sq
