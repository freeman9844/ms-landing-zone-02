import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
SUB = "11111111-1111-1111-1111-111111111111"
POOL_ID = (f"/subscriptions/{SUB}/resourceGroups/rg-lzbegin-ipam/providers/"
           "Microsoft.Network/networkManagers/avnm-lzbegin-ipam/"
           "ipamPools/ipam-lzbegin-shared")
STATE = {
    "schemaVersion": 3, "topology": "avnm-hub-spoke", "runId": "demo123",
    "subscriptionId": SUB, "ipamPoolId": POOL_ID,
    "location": "koreacentral",
    "resourceGroups": {
        "hub": "rg-lzbegin-hub-demo123",
        "spokea": "rg-lzbegin-spokea-demo123",
        "spokeb": "rg-lzbegin-spokeb-demo123",
    },
}


def call(argv, value="", code=0, stderr=""):
    return {"argv": argv, "stdout": value if isinstance(value, str) else json.dumps(value),
            "returncode": code, "stderr": stderr}


def account():
    return call(["account", "show", "--query", "id", "-o", "tsv"], SUB + "\n")


def group(zone):
    name = STATE["resourceGroups"][zone]
    return call(["group", "show", "--name", name, "-o", "json"], {
        "name": name, "id": f"/subscriptions/{SUB}/resourceGroups/{name}",
        "tags": {"workshop": "lz-beginner", "environment": "lab",
                 "runId": "demo123", "managedBy": "workshop"},
    })


def run(script, calls=(), files=None, input_text=None):
    with tempfile.TemporaryDirectory(dir=ROOT) as directory:
        work = Path(directory)
        binary = work / "bin"
        binary.mkdir()
        (work / "scripts").symlink_to(ROOT / "scripts", target_is_directory=True)
        fake = binary / "az"
        shutil.copyfile(ROOT / "tests/fake_az.py", fake)
        fake.chmod(0o700)
        # No real waiting or cloud calls in unit tests.
        (binary / "sleep").write_text("#!/bin/sh\nexit 0\n")
        (binary / "sleep").chmod(0o700)
        # Keep legacy script scratch paths inside this isolated test workspace.
        (binary / "mktemp").write_text(
            "#!/usr/bin/env python3\n"
            "import os, pathlib, subprocess, sys\n"
            "args = [str(pathlib.Path.cwd() / pathlib.Path(a).name) "
            "if a.startswith('/tmp/') else a for a in sys.argv[1:]]\n"
            "sys.exit(subprocess.call(['/usr/bin/mktemp', *args]))\n")
        (binary / "mktemp").chmod(0o700)
        queue = work / "queue.json"
        queue.write_text(json.dumps({"calls": list(calls), "index": 0}))
        content = {"state.json": json.dumps(STATE)}
        content.update(files or {})
        for relative, text in content.items():
            target = work / relative
            if not target.resolve().is_relative_to(work.resolve()):
                raise ValueError("fixture escapes workspace")
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
            if relative.startswith("bin/"):
                target.chmod(0o700)
        env = dict(os.environ, PATH=str(binary) + os.pathsep + os.environ["PATH"],
                   FAKE_AZ_QUEUE=str(queue), WORKSHOP_ROOT=str(ROOT))
        result = subprocess.run(["bash", "-c", script], cwd=work, env=env,
                                input=input_text, text=True, capture_output=True, timeout=30)
        state = json.loads(queue.read_text())
        if state["index"] != len(calls):
            raise AssertionError(f"Unconsumed calls: {state['index']}/{len(calls)}\n{result.stderr}")
        if "FAKE_AZ_ERROR" in result.stderr:
            raise AssertionError(result.stderr)
        return result
