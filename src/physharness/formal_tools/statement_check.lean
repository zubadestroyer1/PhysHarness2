/-
The harness's local-compile statement check, run as
`lake --offline env lean --run statement_check.lean SOURCE.olean REFERENCE.olean NAME`.

SOURCE.olean is the agent's compiled file. REFERENCE.olean is the harness's compile of
`<node header> theorem NAME <node statement> := sorry`. Both are loaded as data: this
program elaborates no agent syntax and runs none of the agent's code, so the agent's
instances, macros, elaborators and options cannot change what it reports. It
1. replays every declaration of SOURCE through the kernel over SOURCE's imports, so a
   declaration added with `debug.skipKernelTC` (or otherwise unchecked) is rejected;
2. compares the replayed NAME's type and universe parameters with the reference theorem's,
   each type with its own module's definitions and theorems unfolded; the unfolded
   reference type's constants must all come from the reference's imports;
3. collects NAME's axioms from the replayed environment (not from `#print axioms` output).
It prints one line: `PHYSHARNESS_STATEMENT_CHECK <json>`.

Compiling SOURCE, before this program runs, executes the file's compile-time code in the
same VM, which can alter this file, REFERENCE or the imported .olean files it trusts (only
SOURCE's own declarations are replayed). The verdict is VM-attested evidence.
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

def constantMap (data : ModuleData) : Std.HashMap Name ConstantInfo := Id.run do
  let mut constants := {}
  for n in data.constNames, c in data.constants do
    constants := constants.insert n c
  return constants

/-- `e` with each constant `defined` holds (a definition or theorem of that module)
replaced, recursively, by its value. The elaborator gives a statement auxiliary
constants (a matcher `NAME.match_1` for each `match`, say), named after the theorem or
reused from an earlier declaration with the same value; unfolded, equal statements are
equal expressions whatever those constants are called. Unfolding is definitional, so
the unfolded statement means what the statement means. -/
partial def unfoldDefined (defined : Std.HashMap Name ConstantInfo) (e : Expr) : Expr :=
  e.replace fun
    | .const n us => do
      let info ← defined.get? n
      let value ← info.value?  -- a definition's or theorem's; none for an opaque
      some (unfoldDefined defined (value.instantiateLevelParams info.levelParams us))
    | _ => none

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
  -- The statement must mean the same thing in both files: unfolded, only imported
  -- constants.
  let expectedType := unfoldDefined (constantMap reference) expected.type
  if expectedType.getUsedConstants.any reference.constNames.contains then
    return ← reject "statement_defines_constants"
  let some (.thmInfo _) := findConstant source name | reject "theorem_missing"
  let env ← try importModules source.imports {} (loadExts := false)
    catch e => return ← reject "import_failed" (toString e)
  unless reference.imports.all (env.header.moduleNames.contains ·.module) do
    return ← reject "imports_differ"
  if env.contains name then return ← reject "name_imported"
  let constants := constantMap source
  let env ← try env.replay constants
    catch e => return ← reject "kernel_rejected" (toString e)
  let some (.thmInfo checked) := env.toKernelEnv.find? name | reject "theorem_missing"
  -- The source's own constants were just kernel-checked, so unfolding them is sound.
  unless checked.levelParams == expected.levelParams
      && unfoldDefined constants checked.type == expectedType do
    return ← reject "statement_mismatch"
  let axioms ← axiomsOf env name
  emit [("ok", true), ("axioms", toJson (axioms.map toString))]
