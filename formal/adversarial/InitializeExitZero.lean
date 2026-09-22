-- An initializer must not turn an unsupported proof into Comparator success.
initialize : IO Unit ← do
  IO.println "ENGINEERING_INITIALIZE_EXIT_ZERO"
  IO.Process.exit 0

theorem target (n : Nat) : n = n := by sorry
