-- A successful compiler process exit must not replace the missing theorem export.
#eval (do
  IO.println "ENGINEERING_COMPILE_EXIT_ZERO"
  IO.Process.exit 0 : IO Unit)

-- Deliberately no target declaration.
