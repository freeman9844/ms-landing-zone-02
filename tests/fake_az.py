#!/usr/bin/env python3
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

path = Path(os.environ["FAKE_AZ_QUEUE"])
state = json.loads(path.read_text())
index = state["index"]
if index >= len(state["calls"]):
    sys.exit(f"FAKE_AZ_ERROR: unexpected call {sys.argv[1:]}")
expected = state["calls"][index]
actual = sys.argv[1:]
matches = len(actual) == len(expected["argv"]) and all(
    bool(re.fullmatch(want["regex"], got)) if isinstance(want, dict) else got == want
    for want, got in zip(expected["argv"], actual))
if not matches:
    sys.exit(f"FAKE_AZ_ERROR: expected {expected['argv']}, got {actual}")
state["index"] += 1
path.write_text(json.dumps(state))
if expected.get("run_guest"):
    script = actual[actual.index("--scripts") + 1]
    guest_path = Path(script[1:]).resolve()
    if not script.startswith("@") or guest_path.parent != path.parent or not guest_path.name.startswith("lzbegin-run."):
        sys.exit("FAKE_AZ_ERROR: unexpected local guest script path")
    Path(script[1:]).chmod(0o700)
    result = subprocess.run(["/bin/sh", "-c", shlex.quote(script[1:])],
                            text=True, capture_output=True, timeout=5)
    print(json.dumps({"value": [
        {"code": "ProvisioningState/succeeded", "level": "Info",
         "displayStatus": "Provisioning succeeded",
         "message": f"Enable succeeded: \n[stdout]\n{result.stdout}\n[stderr]\n{result.stderr}"},
    ]}))
    sys.exit(0)
sys.stdout.write(expected.get("stdout", ""))
sys.stderr.write(expected.get("stderr", ""))
sys.exit(expected.get("returncode", 0))
