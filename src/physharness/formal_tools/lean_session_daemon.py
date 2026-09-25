"""Lean REPL session for the offline workspace VM (Python standard library only).

The host uploads this file into the workspace and runs one of:

  serve   --socket PATH --cwd DIR --repl CMD...    one REPL behind a UNIX socket
  request --socket PATH --timeout S [--cwd --repl] JSON request on stdin, JSON on stdout;
                                                   starts the server when it is missing
  inline  --timeout S [--cwd --repl]               the same request against a private REPL
                                                   that is killed before the command exits

REPL framing: JSON commands separated by a blank line; each response ends at a blank line.
Ops: check {source, automation, extract_goals, axiom_names}, tactics {proof_state,
generation, tactics, stop_on_success}, status and shutdown. Every response is bounded so
that it fits the workspace command's 64 KiB stdout capture.
"""

import argparse
import fcntl
import json
import os
import re
import select
import signal
import socket
import subprocess
import sys
import time

DEFAULT_REPL = ("lake", "env", "/opt/lean-repl/.lake/build/bin/repl")
DEFAULT_CWD = "/opt/sources/physlib"
MAX_COMMANDS = 200
START_WAIT_SECONDS = 180
MAX_STRING = 20000
MAX_RESPONSE_BYTES = 60000
MAX_REQUEST_BYTES = 4 * 1024 * 1024
MAX_REPL_OUTPUT = 64 * 1024 * 1024
MAX_MESSAGES = 50
MAX_SORRIES = 32
MAX_TACTICS = 16
MAX_TACTIC_ITEMS = 8
MAX_NAMES = 32
SORRY_WARNING = re.compile(r"declaration uses ['`]sorry['`]")
_AXIOMS = re.compile(r"'([^'\n]+)' depends on axioms: \[([^\]]*)\]")
_NO_AXIOMS = re.compile(r"'([^'\n]+)' does not depend on any axioms")


def split_header(source):
    """Split leading import/open/set_option lines (with comments between them) from the body.

    ``header + "\\n" + body == source`` whenever the header is non-empty; the body keeps the
    source's line numbering after ``len(header.split("\\n"))`` lines.
    """
    lines = source.split("\n")
    end, in_comment, continues = 0, False, False
    for index, line in enumerate(lines):
        stripped = line.strip()
        if in_comment:
            in_comment = "-/" not in stripped
            continue
        if not stripped or stripped.startswith("--"):
            continues = continues and bool(stripped)
            continue
        if stripped.startswith("/-") and not stripped.startswith("/--"):
            in_comment = "-/" not in stripped[2:]
            continue
        if continues and line[:1].isspace():
            end = index + 1
            continue
        tokens = stripped.split("--", 1)[0].split()
        if tokens[0] == "import" or (tokens[0] in ("public", "meta") and "import" in tokens[1:3]):
            end, continues = index + 1, False
            continue
        if tokens[0] in ("open", "set_option") and "in" not in tokens:
            end, continues = index + 1, True
            continue
        break
    return "\n".join(lines[:end]), "\n".join(lines[end:])


def parse_axioms(text):
    found = {}
    for pattern in (_NO_AXIOMS, _AXIOMS):
        for match in pattern.finditer(text):
            if len(found) < MAX_NAMES or match.group(1) in found:
                axioms = match.group(2).split(",") if pattern is _AXIOMS else []
                found[match.group(1)] = [a.strip() for a in axioms if a.strip()][:MAX_NAMES]
    return found


def select_messages(messages, limit):
    """Keep at most ``limit`` messages, errors first, then warnings, in source order."""
    if len(messages) <= limit:
        return list(messages)
    rank = {"error": 0, "warning": 1}
    order = sorted(
        range(len(messages)), key=lambda i: (rank.get(messages[i].get("severity"), 2), i)
    )
    return [messages[i] for i in sorted(order[:limit])]


def try_this(messages):
    for message in messages:
        data = str(message.get("data", ""))
        if message.get("severity", "info") == "info" and "Try this:" in data:
            text = data.split("Try this:", 1)[1].strip()
            if text.startswith("[apply]"):
                text = text[len("[apply]") :].strip()
            return text or None
    return None


def clip(value, limit):
    if isinstance(value, str):
        return value if len(value) <= limit else value[: limit - 1] + "…"
    if isinstance(value, list):
        return [clip(item, limit) for item in value]
    if isinstance(value, dict):
        return {key: clip(item, limit) for key, item in value.items()}
    return value


def encode(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def fit(response):
    """Encode a response, shortening strings until it fits MAX_RESPONSE_BYTES."""
    for limit in (MAX_STRING, 8000, 4000, 2000, 1000, 500, 250, 120):
        clipped = clip(response, limit)
        if clipped != response:
            clipped["truncated"] = True
        data = encode(clipped)
        if len(data) <= MAX_RESPONSE_BYTES:
            return data
    return encode({"error": "response_too_large", "op": str(response.get("op"))[:40]})


def _shift(item, offset):
    shifted = dict(item)
    for key in ("pos", "endPos"):
        position = item.get(key)
        if isinstance(position, dict) and isinstance(position.get("line"), int):
            shifted[key] = dict(position, line=position["line"] + offset)
    return shifted


def _group_alive(pgid):
    if os.path.isdir("/proc"):
        for entry in os.listdir("/proc"):
            if not entry.isdigit():
                continue
            try:
                with open("/proc/" + entry + "/stat") as stream:
                    fields = stream.read().rsplit(")", 1)[1].split()
            except (OSError, IndexError):
                continue
            if len(fields) > 2 and fields[0] != "Z" and fields[2] == str(pgid):
                return True
        return False
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def terminate_group(process):
    """Kill a process group and wait until no live member remains (zombies aside)."""
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        pass
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        pass
    for stream in (process.stdin, process.stdout):
        try:
            stream.close()
        except (OSError, AttributeError):
            pass
    limit = time.monotonic() + 5
    while time.monotonic() < limit and _group_alive(process.pid):
        time.sleep(0.02)


class ReplError(Exception):
    def __init__(self, code, detail=""):
        super().__init__(code)
        self.code, self.detail = code, detail


class Repl:
    """One REPL process in its own process group."""

    def __init__(self, argv, cwd):
        try:
            self.process = subprocess.Popen(
                list(argv),
                cwd=cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                bufsize=0,
                start_new_session=True,
            )
        except OSError as exc:
            raise ReplError("repl_start_failed", str(exc)) from exc
        os.set_blocking(self.process.stdin.fileno(), False)
        self.buffer = b""

    def call(self, command, deadline):
        data = memoryview(encode(command) + b"\n\n")
        fd = self.process.stdin.fileno()
        while data:
            self._wait([], [fd], deadline)
            try:
                data = data[os.write(fd, data[:65536]) :]
            except BlockingIOError:
                continue
            except OSError as exc:
                raise ReplError("repl_crashed", str(exc)) from exc
        fd = self.process.stdout.fileno()
        while True:
            self.buffer = self.buffer.lstrip()
            head, separator, rest = self.buffer.partition(b"\n\n")
            if separator:
                self.buffer = rest
                try:
                    response = json.loads(head.decode("utf-8", "replace"))
                except ValueError:
                    response = None
                if not isinstance(response, dict):
                    raise ReplError("repl_protocol_error", head[:500].decode("utf-8", "replace"))
                return response
            if len(self.buffer) > MAX_REPL_OUTPUT:
                raise ReplError("repl_protocol_error", "REPL response exceeds the output bound")
            self._wait([fd], [], deadline)
            chunk = os.read(fd, 1 << 16)
            if not chunk:
                raise ReplError("repl_crashed", f"REPL exited with status {self.process.poll()}")
            self.buffer += chunk

    @staticmethod
    def _wait(readers, writers, deadline):
        remaining = deadline - time.monotonic()
        if remaining <= 0 or not any(select.select(readers, writers, [], remaining)):
            raise ReplError("timeout", "Lean did not answer before the deadline")

    def close(self):
        terminate_group(self.process)


class Session:
    """REPL lifecycle: header env cache, proof-state generations and restarts."""

    def __init__(self, repl_argv, cwd, max_commands=MAX_COMMANDS):
        self.repl_argv, self.cwd, self.max_commands = list(repl_argv), cwd, max_commands
        self.repl, self.generation = None, 0
        self.reset()

    def reset(self):
        if self.repl is not None:
            self.repl.close()
        self.repl, self.commands, self.envs, self.proof_states = None, 0, {}, set()

    def send(self, command, deadline):
        if self.repl is None:
            self.repl = Repl(self.repl_argv, self.cwd)
            self.generation += 1
        try:
            response = self.repl.call(command, deadline)
        except ReplError:
            self.reset()
            raise
        self.commands += 1
        return response

    def handle(self, request, deadline):
        op = request.get("op")
        try:
            if op == "check":
                return self.check(request, deadline)
            if op == "tactics":
                return self.tactics(request, deadline)
            if op == "status":
                return self.status()
        except ReplError as exc:
            return {"error": exc.code, "detail": exc.detail, "generation": self.generation}
        return {"error": "bad_request", "detail": "unknown or malformed op"}

    def status(self):
        running = self.repl is not None and self.repl.process.poll() is None
        return {
            "op": "status",
            "generation": self.generation,
            "running": running,
            "commands": self.commands,
            "headers_cached": len(self.envs),
            "proof_states": len(self.proof_states),
            "pid": os.getpid(),
        }

    def check(self, request, deadline):
        source, automation = request.get("source"), request.get("automation") or []
        names = request.get("axiom_names") or []
        if (
            not isinstance(source, str)
            or not _strings(automation, MAX_TACTICS)
            or not _strings(names, MAX_NAMES)
        ):
            return {"error": "bad_request", "detail": "malformed check request"}
        if self.commands >= self.max_commands:
            self.reset()
        header, body = split_header(source)
        offset = len(header.split("\n")) if header else 0
        cached, header_messages, command = False, [], {"cmd": body}
        if header:
            entry = self.envs.get(header)
            cached = entry is not None
            if entry is None:
                response = self.send({"cmd": header}, deadline)
                if not isinstance(response.get("env"), int):
                    return _repl_error(response)
                entry = self.envs[header] = (response["env"], response.get("messages") or [])
            command["env"], header_messages = entry
        response = self.send(command, deadline)
        if not isinstance(response.get("env"), int):
            return _repl_error(response)
        messages = header_messages + [_shift(m, offset) for m in response.get("messages") or []]
        sorries = [_shift(s, offset) for s in response.get("sorries") or []]
        self.proof_states.update(s["proofState"] for s in sorries if _integer(s.get("proofState")))
        errors = sum(1 for m in messages if m.get("severity") == "error")
        warnings = sum(
            1
            for m in messages
            if m.get("severity") == "warning" and SORRY_WARNING.match(str(m.get("data", "")))
        )
        result = {
            "op": "check",
            "generation": self.generation,
            "header_cached": cached,
            "env": response["env"],
            "counts": {
                "errors": errors,
                "messages": len(messages),
                "sorries": len(sorries),
                "sorry_warnings": warnings,
            },
            "messages": select_messages(messages, MAX_MESSAGES),
            "sorries": [
                {
                    "pos": s.get("pos"),
                    "endPos": s.get("endPos"),
                    "goal": s.get("goal"),
                    "proofState": s.get("proofState"),
                    "automation": None,
                    "extracted": None,
                }
                for s in sorries[:MAX_SORRIES]
            ],
            "axioms": None,
        }
        if len(messages) > MAX_MESSAGES or len(sorries) > MAX_SORRIES:
            result["truncated"] = True
        # Automation may not starve goal extraction of its reserve.
        reserve = min(20.0, max(1.0, (deadline - time.monotonic()) / 4))
        for hole in result["sorries"]:
            state = hole["proofState"]
            if automation and _integer(state):
                hole["automation"] = self.run_tactics(state, automation, True, deadline - reserve)
                hole["automation"].pop("results")
                if "error" in hole["automation"]:
                    result["phase_error"] = hole["automation"]["error"]
                    return result
        for hole in result["sorries"] if request.get("extract_goals") else []:
            closed = hole["automation"] and hole["automation"]["closed_by"]
            if _integer(hole["proofState"]) and not closed:
                outcome = self.run_tactics(hole["proofState"], ["extract_goal"], False, deadline)
                if "error" in outcome:
                    result["phase_error"] = outcome["error"]
                    return result
                infos = [m for r in outcome["results"] for m in r["messages"]]
                hole["extracted"] = next(
                    (str(m.get("data")) for m in infos if "theorem" in str(m.get("data", ""))),
                    None,
                )
        if names and not errors and not sorries and not warnings:
            # The declarations already live in the body's env; only the report is new.
            command = {"cmd": "\n".join("#print axioms " + n for n in names)}
            try:
                printed = self.send(dict(command, env=response["env"]), deadline)
            except ReplError as exc:
                result["phase_error"] = exc.code
                return result
            texts = [str(m.get("data", "")) for m in printed.get("messages") or []]
            result["axioms"] = parse_axioms("\n".join(texts))
        return result

    def tactics(self, request, deadline):
        state, tactics = request.get("proof_state"), request.get("tactics")
        generation = request.get("generation", self.generation)
        if not _integer(state) or not _strings(tactics, MAX_TACTICS):
            return {"error": "bad_request", "detail": "malformed tactics request"}
        if self.repl is None or generation != self.generation or state not in self.proof_states:
            return {"error": "proof_state_expired"}
        outcome = self.run_tactics(state, tactics, request.get("stop_on_success", True), deadline)
        outcome.update(op="tactics", generation=self.generation)
        return outcome

    def run_tactics(self, state, tactics, stop_on_success, deadline):
        outcome = {"closed_by": None, "suggestion": None, "tried": [], "results": []}
        for tactic in tactics:
            outcome["tried"].append(tactic)
            try:
                response = self.send({"tactic": tactic, "proofState": state}, deadline)
            except ReplError as exc:
                outcome["error"] = exc.code
                return outcome
            if _integer(response.get("proofState")):
                self.proof_states.add(response["proofState"])
            messages = response.get("messages") or []
            closed = (
                response.get("goals") == []
                and "message" not in response
                and response.get("proofStatus", "Completed") == "Completed"
                and not any(m.get("severity") == "error" for m in messages)
            )
            goals = response.get("goals") if isinstance(response.get("goals"), list) else []
            outcome["results"].append(
                {
                    "tactic": tactic,
                    "closed": closed,
                    "goals": goals[:MAX_TACTIC_ITEMS],
                    "messages": select_messages(messages, MAX_TACTIC_ITEMS),
                    "error": response.get("message"),
                }
            )
            suggestion = try_this(messages)
            if closed and outcome["closed_by"] is None:
                outcome["closed_by"] = tactic
                outcome["suggestion"] = suggestion or outcome["suggestion"]
                if stop_on_success:
                    break
            elif outcome["suggestion"] is None:
                outcome["suggestion"] = suggestion
        return outcome


def _integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _strings(values, limit):
    return (
        isinstance(values, list)
        and len(values) <= limit
        and all(isinstance(v, str) and 0 < len(v) <= 200 for v in values)
    )


def _repl_error(response):
    return {"error": "repl_error", "detail": str(response.get("message", response))[:2000]}


def _receive(conn, limit, deadline):
    chunks, size = [], 0
    while True:
        conn.settimeout(max(0.01, deadline - time.monotonic()))
        chunk = conn.recv(1 << 16)
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        size += len(chunk)
        if size > limit:
            raise ValueError("message exceeds its size bound")


def _decode_request(data):
    request = json.loads(data.decode("utf-8"))
    if not isinstance(request, dict):
        raise ValueError("request must be a JSON object")
    return request


def _emit(data):
    sys.stdout.buffer.write(data if isinstance(data, bytes) else fit(data))
    sys.stdout.buffer.flush()


def _read_stdin():
    data = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
    if len(data) > MAX_REQUEST_BYTES:
        raise ValueError("request exceeds its size bound")
    return _decode_request(data)


def serve(args):
    session = Session(args.repl, args.cwd, args.max_commands)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        os.unlink(args.socket)
    except FileNotFoundError:
        pass
    previous = os.umask(0o077)
    try:
        listener.bind(args.socket)
    finally:
        os.umask(previous)
    listener.listen(16)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    try:
        while True:
            conn, _ = listener.accept()
            with conn:
                try:
                    request = _decode_request(
                        _receive(conn, MAX_REQUEST_BYTES, time.monotonic() + 30)
                    )
                except (OSError, ValueError) as exc:
                    request = {"op": "invalid", "detail": str(exc)}
                if request.get("op") == "shutdown":
                    _send(conn, encode({"op": "shutdown"}))
                    return
                _send(conn, fit(_handle(session, request, _deadline(request))))
    finally:
        session.reset()
        listener.close()
        try:
            os.unlink(args.socket)
        except OSError:
            pass


def _deadline(request):
    try:
        remaining = float(request.get("deadline")) - time.time()
    except (TypeError, ValueError):
        remaining = 120.0
    return time.monotonic() + min(max(remaining, 0.05), 86400.0)


def _handle(session, request, deadline):
    try:
        return session.handle(request, deadline)
    except Exception as exc:  # A daemon bug must not take the session down with it.
        return {"error": "internal_error", "detail": repr(exc)[:2000]}


def _send(conn, data):
    try:
        conn.settimeout(30)
        conn.sendall(data)
    except OSError:
        pass  # The client gave up; the next request finds the session intact.


def _connect(path):
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        conn.connect(path)
    except OSError:
        conn.close()
        raise
    return conn


def _start_server(args, deadline):
    """Connect to the server, starting it detached (new session, no inherited stdio)."""
    try:
        return _connect(args.socket), None
    except OSError:
        pass
    lock = os.open(args.socket + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    return None, "timed out waiting for the server start lock"
                time.sleep(0.05)
        try:
            return _connect(args.socket), None
        except OSError:
            pass
        log_path = args.socket + ".log"
        with open(log_path, "wb") as log:
            server = subprocess.Popen(
                [sys.executable, os.path.abspath(__file__), "serve", "--socket", args.socket]
                + ["--cwd", args.cwd, "--repl"]
                + list(args.repl),
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
                close_fds=True,
            )
        limit = min(deadline, time.monotonic() + START_WAIT_SECONDS)
        while time.monotonic() < limit:
            try:
                return _connect(args.socket), None
            except OSError:
                pass
            if server.poll() is not None:
                with open(log_path, "rb") as log:
                    tail = log.read()[-2000:].decode("utf-8", "replace")
                return None, f"server exited with status {server.returncode}: {tail}"
            time.sleep(0.02)
        return None, "server was not ready before the deadline"
    finally:
        os.close(lock)


def request_main(args):
    request = _read_stdin()
    deadline = time.monotonic() + args.timeout
    conn, problem = _start_server(args, deadline)
    if conn is None:
        return _emit({"error": "server_start_failed", "detail": problem})
    request["deadline"] = time.time() + max(0.05, deadline - time.monotonic() - 1.0)
    with conn:
        try:
            conn.sendall(encode(request))
            conn.shutdown(socket.SHUT_WR)
            data = _receive(conn, 2 * MAX_RESPONSE_BYTES, deadline + 1.0)
        except TimeoutError:
            return _emit({"error": "timeout", "detail": "no answer before the client deadline"})
        except (OSError, ValueError) as exc:
            return _emit({"error": "server_failed", "detail": str(exc)})
    _emit(data if data else {"error": "server_failed", "detail": "empty answer"})


def inline_main(args):
    request = _read_stdin()
    session = Session(args.repl, args.cwd)
    try:
        response = _handle(session, request, time.monotonic() + args.timeout)
    finally:
        session.reset()
    _emit(response)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="lean_session")
    modes = parser.add_subparsers(dest="mode", required=True)
    for name in ("serve", "request", "inline"):
        mode = modes.add_parser(name)
        if name != "inline":
            mode.add_argument("--socket", required=True)
        if name != "serve":
            mode.add_argument("--timeout", type=float, required=True)
        mode.add_argument("--cwd", default=DEFAULT_CWD)
        mode.add_argument("--repl", nargs="+", default=list(DEFAULT_REPL))
        mode.add_argument("--max-commands", type=int, default=MAX_COMMANDS)
    args = parser.parse_args(argv)
    try:
        {"serve": serve, "request": request_main, "inline": inline_main}[args.mode](args)
    except ValueError as exc:
        _emit({"error": "bad_request", "detail": str(exc)[:2000]})


if __name__ == "__main__":
    main()
