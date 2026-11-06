#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Real native lock-graph and explicit-purity regressions for SDK sources."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / "tools"))
import jvm_sdk_sources


def run(command):
    result = subprocess.run(command, text=True, capture_output=True)
    return {"argv": command, "exitCode": result.returncode,
            "stdout": result.stdout, "stderr": result.stderr}


parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
report = {"scope": "native source graphs and pure evaluation, no Gradle role support claim",
          "sourceHashes": {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in [root / "tools/jvm_sdk_sources.py", Path(__file__)]},
          "cases": []}


def save():
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")


try:
    source = json.loads((root / "flake.lock").read_text())["nodes"]["nixpkgs"]["locked"]
    source = {key: source[key] for key in ("type", "owner", "repo", "rev", "narHash")}
    report["realImmutableSource"] = jvm_sdk_sources.validate_source_graph(source)
    reference = "github:" + source["owner"] + "/" + source["repo"] + "/" + source["rev"]
    with tempfile.TemporaryDirectory(prefix="purifier-jvm-sdk-source-") as temporary:
        temporary = Path(temporary)
        definitions = {
            "no-inputs": '{ outputs = { self }: {}; }',
            "missing-lock": '{ inputs.sdk.url = ' + json.dumps(reference)
                            + '; outputs = { self, ... }: {}; }',
            "incomplete-lock": '{ inputs.sdk.url = ' + json.dumps(reference)
                               + '; outputs = { self, ... }: {}; }',
            "stale-lock": '{ inputs.sdk.url = ' + json.dumps(reference)
                          + '; outputs = { self, ... }: {}; }',
            "unlocked-node": '{ inputs.sdk.url = ' + json.dumps(reference)
                             + '; outputs = { self, ... }: {}; }',
            "cycle": '{ inputs.a.follows="b"; inputs.b.follows="a"; outputs={self,...}:{}; }',
            "root-follows": '{ inputs.a.follows=""; outputs={self,...}:{}; }',
        }
        for name, definition in definitions.items():
            path = temporary / name
            path.mkdir()
            (path / "flake.nix").write_text(definition + "\n")
            if name == "incomplete-lock":
                (path / "flake.lock").write_text(json.dumps({
                    "nodes": {"root": {}}, "root": "root", "version": 7}))
            if name in {"stale-lock", "unlocked-node"}:
                node = {"original": {key: value for key, value in source.items() if key != "narHash"}}
                if name == "stale-lock":
                    node["locked"] = source
                (path / "flake.lock").write_text(json.dumps({
                    "nodes": {"root": {"inputs": {
                        "old" if name == "stale-lock" else "sdk": "sdk"}}, "sdk": node},
                    "root": "root", "version": 7}))
            if name == "root-follows":
                (path / "flake.lock").write_text(json.dumps({
                    "nodes": {"root": {"inputs": {"a": []}}}, "root": "root", "version": 7}))
            before = {p.name: p.read_bytes() for p in path.iterdir()}
            base = ["nix", "flake", "metadata", "path:" + str(path), "--json",
                    "--no-update-lock-file", "--no-use-registries", "--offline",
                    "--option", "pure-eval", "true",
                    "--option", "allow-import-from-derivation", "false"]
            result = run(base)
            result["case"] = name
            report["cases"].append(result)
            save()
            assert (result["exitCode"] == 0) == (name in {"no-inputs", "root-follows"}), result
            if result["exitCode"] == 0:
                metadata = json.loads(result["stdout"])
                result["sourceLock"] = jvm_sdk_sources.validate_source_lock(
                    metadata["path"], metadata["locks"])
            else:
                counter = run(base + ["--no-write-lock-file"])
                counter["case"] = name + "-forbidden-no-write-combination"
                report["cases"].append(counter)
                if name not in {"cycle", "unlocked-node"}:
                    assert counter["exitCode"] == 0, counter
                    metadata = json.loads(counter["stdout"])
                    try:
                        jvm_sdk_sources.validate_source_lock(metadata["path"], metadata["locks"])
                    except ValueError:
                        counter["inMemoryGraphRejected"] = True
                    else:
                        raise AssertionError("an in-memory refreshed source graph was accepted")
            assert before == {p.name: p.read_bytes() for p in path.iterdir()}
        # Explicit purity is required: --file alone previously exposed getEnv.
        for name, expression, accepted in [
            ("environment", 'builtins.getEnv "PATH"', True),
            ("implicit-system", "builtins.currentSystem", False),
            ("implicit-time", "builtins.currentTime", False),
            ("outside-path", "builtins.readFile " + str(root / "flake.nix"), False),
        ]:
            result = run(["nix", "eval", "--json", "--expr", expression,
                          "--option", "pure-eval", "true",
                          "--option", "allow-import-from-derivation", "false"])
            result["case"] = name
            report["cases"].append(result)
            assert (result["exitCode"] == 0) == accepted, result
            if name == "environment":
                assert json.loads(result["stdout"]) == ""
        expression = ('let source=builtins.fromJSON ' + json.dumps(json.dumps(source))
                      + '; pkgs=import (builtins.fetchTree source).outPath '
                      + '{system="x86_64-linux";config={};overlays=[];}; '
                      + 'in builtins.readFile (pkgs.writeText "forbidden-sdk-source-ifd" "marker")')
        result = run(["nix", "eval", "--json", "--expr", expression, "--offline",
                      "--option", "pure-eval", "true",
                      "--option", "allow-import-from-derivation", "false"])
        result["case"] = "import-from-derivation"
        report["cases"].append(result)
        assert result["exitCode"] != 0 and "allow-import-from-derivation" in result["stderr"], result
    report["status"] = "passed"
finally:
    save()
print("JVM SDK SOURCE GRAPHS AND EXPLICIT PURITY VERIFIED")
