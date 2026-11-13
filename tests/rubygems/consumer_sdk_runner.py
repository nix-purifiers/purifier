# SPDX-License-Identifier: MIT
"""The probe deadline must include parent exit and inherited pipe EOF."""

import importlib.util
import os
from pathlib import Path
import sys, time

spec = importlib.util.spec_from_file_location(
    "consumer_sdk",
    Path(__file__).resolve().parents[2] / "tools/rubygems_consumer_sdk.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
# Parent cleanup must never signal a numeric group ID. The supervisor owns
# self-signalling in its separate interpreter.
def forbidden_parent_signal(*args):
    raise AssertionError("parent attempted process-group signalling")


killpg = os.killpg
module.os.killpg = forbidden_parent_signal
assert module.run([sys.executable, "-c", 'print("ordinary")']).strip() == "ordinary"
cases = [
    ("nonzero", "import sys;sys.exit(7)", "command failed", 90, 8388608),
    (
        "orphan-pipe",
        "import os,time;pid=os.fork();os._exit(0) if pid else time.sleep(60)",
        "deadline",
        0.3,
        8388608,
    ),
    (
        "closed-pipe-parent",
        "import os,time;os.close(1);os.close(2);time.sleep(60)",
        "deadline",
        0.3,
        8388608,
    ),
    ("output-limit", 'import os;os.write(1,b"x"*65536)', "output exceeds", 90, 4096),
    (
        "live-stderr-limit",
        'import os,time;os.write(2,b"x"*65536);time.sleep(60)',
        "output exceeds",
        90,
        4096,
    ),
]
for name, code, expected, deadline, limit in cases:
    start = time.monotonic()
    rejected = False
    try:
        module.run(
            [sys.executable, "-c", code], deadline_seconds=deadline, output_limit=limit
        )
    except ValueError as error:
        assert expected in str(error), (name, error)
        rejected = True
    assert rejected, name
    assert time.monotonic() - start < 5, name
# A missing executable reports a bounded startup failure, then cleans up.
try:
    module.run(["/nonexistent-purifier-sdk-command"])
except ValueError as error:
    assert "command failed" in str(error)
else:
    raise AssertionError("missing command accepted")

# Test real descendants with a delayed external effect. Synchronize their
# startup so an absent marker demonstrates cleanup, not a failed fork.
import tempfile
import fcntl


def assert_released(path):
    # The fixture holds this lock until process exit; zombies release it too.
    with open(path, "a") as lock:
        deadline = time.monotonic() + 1
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except BlockingIOError:
                assert time.monotonic() < deadline, "fixture process still owns lock"
                time.sleep(0.01)

with tempfile.TemporaryDirectory() as temporary:
    markers = []
    for mode in ("orphan-pipe", "output-limit", "closed-orphan"):
        marker = str(Path(temporary) / mode)
        markers.append(marker)
        code = """
import fcntl, os, sys, time
read, write = os.pipe()
pid = os.fork()
if pid == 0:
    os.close(read)
    lock = open(sys.argv[1] + ".lock", "w")
    fcntl.flock(lock, fcntl.LOCK_EX)
    open(sys.argv[1] + ".pid", "w").write(str(os.getpid()))
    if sys.argv[2] == "closed-orphan":
        os.close(1)
        os.close(2)
    os.write(write, b"R")
    os.close(write)
    time.sleep(2)
    open(sys.argv[1], "w").write("leaked descendant")
    os._exit(0)
os.close(write)
os.read(read, 1)
os.close(read)
if sys.argv[2] == "output-limit":
    os.write(1, b"x" * 65536)
    time.sleep(2)
os._exit(0)
"""
        try:
            result = module.run(
                [sys.executable, "-c", code, marker, mode],
                deadline_seconds=1,
                output_limit=4096,
            )
        except ValueError as error:
            assert mode != "closed-orphan", error
            assert ("output exceeds" if mode == "output-limit" else "deadline") in str(error)
        else:
            assert mode == "closed-orphan" and result == ""
        pid = int(Path(marker + ".pid").read_text())
        assert pid > 1 and pid != os.getpid(), "descendant did not start"
        assert_released(marker + ".lock")
    time.sleep(2.2)
    assert all(not Path(marker).exists() for marker in markers), markers
    # Losing the caller closes control while the command is still alive.
    # The supervisor must observe EOF without waiting for that command to exit.
    import subprocess

    ready = str(Path(temporary) / "parent-ready")
    marker = str(Path(temporary) / "parent-death")
    worker = (
        "import fcntl,pathlib,sys,time;lock=open(sys.argv[2]+'.lock','w');"
        "fcntl.flock(lock,fcntl.LOCK_EX);pathlib.Path(sys.argv[1]).touch();"
        "time.sleep(1);pathlib.Path(sys.argv[2]).write_text('leaked worker')"
    )
    caller = """
import importlib.util, sys
spec = importlib.util.spec_from_file_location("sdk", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.run([sys.executable, "-c", sys.argv[2], sys.argv[3], sys.argv[4]])
"""
    parent = subprocess.Popen(
        [sys.executable, "-B", "-c", caller, str(Path(module.__file__)), worker, ready, marker],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 3
        while not Path(ready).exists():
            assert parent.poll() is None and time.monotonic() < deadline
            time.sleep(0.01)
        parent.kill()
    finally:
        if parent.poll() is None:
            parent.kill()
        parent.wait(timeout=5)
    assert_released(marker + ".lock")
    time.sleep(1.2)
    assert not Path(marker).exists(), "control EOF left a live worker"
module.os.killpg = killpg
print(
    "Ordinary SDK runner: output, exit, orphan pipe, closed pipe live parent, "
    "output bounds, descendant cleanup, caller death, missing command and no parent signals PASS"
)
