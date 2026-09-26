/-
The harness's local-compile statement check, run as
`lake --offline env lean --run statement_check.lean SOURCE.olean REFERENCE.olean NAME`.

SOURCE.olean is the agent's compiled file. REFERENCE.olean is the harness's compile of
`<node header> theorem NAME <node statement> := sorry`. Both are read as data: this program
elaborates no agent syntax and runs none of the agent's code, so the agent's instances,
macros, elaborators and options cannot change what it reports. It
1. replays every declaration of SOURCE through the kernel over SOURCE's imports, so a
   declaration added with `debug.skipKernelTC` (or otherwise unchecked) is rejected;
2. compares the replayed NAME's type and universe parameters with the reference theorem's,
   whose constants must all come from the reference's imports;
3. collects NAME's axioms from the replayed environment (not from `#print axioms` output).
It prints one line: `PHYSHARNESS_STATEMENT_CHECK <json>`.
-/
import Lean
open Lean

def emit (fields : List (String × Json)) : IO UInt32 := do
  IO.println ("PHYSHARNESS_STATEMENT_CHECK " ++ (Json.mkObj fields).compress)
  return 0

def reject (reason : String) (detail : String := "") : IO UInt32 :=
  emit [("ok", false), ("reason", reason), ("detail", (detail.take 1000).toString)]

def findConstant (data : ModuleData) (name : Name) : Option ConstantInfo := Id.run do
  for n in data.constNames, c in data.constants do
    if n == name then return some c
  return none

def axiomsOf (env : Environment) (name : Name) : IO (Array Name) := do
  let (axioms, _) ← (collectAxioms name : CoreM (Array Name)).toIO
    { fileName := "<statement-check>", fileMap := default } { env }
  return axioms

def main (args : List String) : IO UInt32 := do
  let [sourcePath, referencePath, nameText] := args | reject "usage"
  let name := nameText.toName
  initSearchPath (← findSysroot)
  let (source, _) ← readModuleData sourcePath
  let (reference, _) ← readModuleData referencePath
  if source.isModule then return ← reject "module_system_source"
  let some (.thmInfo expected) := findConstant reference name | reject "reference_missing"
  -- The statement must mean the same thing in both files: only imported constants.
  if expected.type.getUsedConstants.any reference.constNames.contains then
    return ← reject "statement_defines_constants"
  let some (.thmInfo _) := findConstant source name | reject "theorem_missing"
  let env ← try importModules source.imports {} (loadExts := false)
    catch e => return ← reject "import_failed" (toString e)
  unless reference.imports.all (env.header.moduleNames.contains ·.module) do
    return ← reject "imports_differ"
  if env.contains name then return ← reject "name_imported"
  let mut constants : Std.HashMap Name ConstantInfo := {}
  for n in source.constNames, c in source.constants do
    constants := constants.insert n c
  let env ← try env.replay constants
    catch e => return ← reject "kernel_rejected" (toString e)
  let some (.thmInfo checked) := env.toKernelEnv.find? name | reject "theorem_missing"
  unless checked.levelParams == expected.levelParams && checked.type == expected.type do
    return ← reject "statement_mismatch"
  let axioms ← axiomsOf env name
  emit [("ok", true), ("axioms", toJson (axioms.map toString))]
