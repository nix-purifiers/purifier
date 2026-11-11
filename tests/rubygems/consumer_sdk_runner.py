# SPDX-License-Identifier: MIT
"""The probe deadline must include parent exit and inherited pipe EOF."""

import importlib.util
from pathlib import Path
import sys, time

spec = importlib.util.spec_from_file_location(
    "consumer_sdk",
    Path(__file__).resolve().parents[2] / "tools/rubygems_consumer_sdk.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
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
print(
    "Ordinary SDK runner: output, exit, orphan pipe, closed pipe live parent and output bounds PASS"
)
