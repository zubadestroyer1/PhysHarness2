"""Local-compile statement check for the offline workspace VM (Python standard library only).

The host uploads this file and ``statement_check.lean`` into the workspace and runs:

  statement_check.py --timeout S --cwd DIR --checker FILE WORKDIR NAME

WORKDIR holds ``Source.lean`` (the agent's file) and ``Reference.lean`` (the harness's
``<node header> theorem NAME <node statement> := sorry``). Each is compiled to an .olean by
``lake --offline env lean -R WORKDIR -o`` in DIR, which runs the file's compile-time code
(``#eval``, ``run_cmd``) with this process's access to the VM. Then ``lake --offline env
lean --run FILE`` runs the harness checker, which loads both .olean files as data and
elaborates no agent syntax: it replays the source's declarations through the kernel,
compares NAME's type with the reference's and collects NAME's axioms. One JSON object goes
to stdout, and WORKDIR is removed. Every step shares the one deadline; a process group that
outlives it is killed.
"""

import argparse
import json
import os
import shutil
import signal
import subprocess
import time

LEAN = ("lake", "--offline", "env", "lean")
MARK = "PHYSHARNESS_STATEMENT_CHECK "
MAX_DETAIL = 1000
MAX_CHECKER_OUTPUT = 1 << 20


def run(argv, cwd, deadline, log):
    """Run argv in its own process group, output to ``log``; its exit status, or None when
    the deadline passed first."""
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        return None
    with open(log, "wb") as out:
        process = subprocess.Popen(
            list(argv),
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            return process.wait(timeout=remaining)
        except subprocess.TimeoutExpired:
            return None
        finally:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except OSError:
                pass
            process.wait()


def tail(path):
    try:
        with open(path, "rb") as stream:
            stream.seek(0, os.SEEK_END)
            stream.seek(max(0, stream.tell() - MAX_DETAIL))
            return stream.read().decode("utf-8", "replace")
    except OSError:
        return ""


def check(workdir, name, cwd, checker, deadline):
    log = os.path.join(workdir, "log.txt")
    oleans = []
    for label in ("Source", "Reference"):
        olean = os.path.join(workdir, label + ".olean")
        # WORKDIR is outside the Lake project DIR, so it is the module root: without one,
        # ``lean -o`` refuses a file outside its working directory.
        source = os.path.join(workdir, label + ".lean")
        status = run([*LEAN, "-R", workdir, "-o", olean, source], cwd, deadline, log)
        if status is None:
            return {"ok": False, "reason": "check_timeout"}
        if status != 0 or not os.path.isfile(olean):
            return {"ok": False, "reason": label.lower() + "_compile_failed", "detail": tail(log)}
        oleans.append(olean)
    status = run([*LEAN, "--run", checker, *oleans, name], cwd, deadline, log)
    if status is None:
        return {"ok": False, "reason": "check_timeout"}
    with open(log, "rb") as stream:
        output = stream.read(MAX_CHECKER_OUTPUT).decode("utf-8", "replace")
    reports = [line[len(MARK) :] for line in output.split("\n") if line.startswith(MARK)]
    verdict = None
    if status == 0 and len(reports) == 1:
        try:
            verdict = json.loads(reports[0])
        except ValueError:
            verdict = None
    if not isinstance(verdict, dict):
        return {"ok": False, "reason": "checker_failed", "detail": tail(log)}
    return verdict


def main(argv=None):
    parser = argparse.ArgumentParser(prog="statement_check")
    parser.add_argument("--timeout", type=float, required=True)
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--checker", required=True)
    parser.add_argument("workdir")
    parser.add_argument("name")
    args = parser.parse_args(argv)
    deadline = time.monotonic() + args.timeout
    workdir, checker = os.path.abspath(args.workdir), os.path.abspath(args.checker)
    try:
        result = check(workdir, args.name, args.cwd, checker, deadline)
    except OSError as exc:
        result = {"ok": False, "reason": "check_failed", "detail": str(exc)[:MAX_DETAIL]}
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
