#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Exercise the real Nix replay guard independently of capture's Python check."""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True
root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / "tools"))
import jvm_sdk_sources

parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
graph_file = root / "lib-overlays/default/jvm-sdk-source-graph.nix"
report = {"scope": "direct Nix graph comparison; path fixtures do not enable path SDK sources",
          "sourceHashes": {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                           for p in [graph_file, Path(__file__)]}, "cases": []}


def command(argv):
    result = subprocess.run(argv, text=True, capture_output=True)
    return {"argv": argv, "exitCode": result.returncode,
            "stdout": result.stdout, "stderr": result.stderr}


def nar(path):
    return subprocess.check_output(["nix", "hash", "path", str(path)], text=True).strip()


try:
    sdk_source = json.loads((root / "flake.lock").read_text())["nodes"]["nixpkgs"]["locked"]
    sdk_source = {key: sdk_source[key] for key in ("type", "owner", "repo", "rev", "narHash")}
    sdk_ref = "github:" + sdk_source["owner"] + "/" + sdk_source["repo"] + "/" + sdk_source["rev"]
    # A published source with a real transitive graph, including native
    # follows. This is a graph fixture, not an SDK provider or support claim.
    transitive_source = {
        "type": "github", "owner": "nix-purifiers", "repo": "gradle-purifier",
        "rev": "82e5106ee2c6c02e57d2d4f256bbca10eab9da25",
        "narHash": "sha256-9cHlHl2lOAbm1f8pLlZmbQf8tYSsL2FXAWWbKaxn2vc=",
    }
    report["transitiveSource"] = jvm_sdk_sources.validate_source_graph(transitive_source)
    child_ref = "github:nix-purifiers/gradle-purifier/" + transitive_source["rev"]
    with tempfile.TemporaryDirectory(prefix="purifier-jvm-sdk-replay-") as temporary:
        temporary = Path(temporary)
        snapshot = temporary / "guard"
        snapshot.mkdir()
        shutil.copy2(graph_file, snapshot / graph_file.name)
        cases = []
        names = ["no-inputs", "root-follows", "diamond", "flake-false", "nested-override",
                 "stale-name", "revision", "selector", "follows-redirect", "nested-follows-redirect",
                 "additional-input", "missing-node", "unreachable-node", "absent-lock"]
        for name in names:
            path = temporary / name
            path.mkdir()
            declarations = "inputs.sdk.url=" + json.dumps(sdk_ref) + ";"
            if name == "no-inputs":
                declarations = ""
            elif name == "root-follows":
                declarations = 'inputs.a.follows="";'
            elif name in {"diamond", "follows-redirect"}:
                declarations = ('inputs.a.url=' + json.dumps(sdk_ref) + ';inputs.b.url='
                                + json.dumps(sdk_ref) + ';inputs.c.follows="a";')
            elif name == "flake-false":
                declarations += "inputs.sdk.flake=false;"
            elif name in {"nested-override", "nested-follows-redirect"}:
                declarations = ('inputs.a.url=' + json.dumps(sdk_ref) + ';inputs.b.url='
                                + json.dumps(sdk_ref) + ';inputs.child.url=' + json.dumps(child_ref)
                                + ';inputs.child.inputs.nixpkgs.follows="a";')
            definition = "{ " + declarations + " outputs={self,...}:{};}\n"
            (path / "flake.nix").write_text(definition)
            if name not in {"no-inputs", "absent-lock"}:
                generation = command(["nix", "flake", "lock", "path:" + str(path),
                                      "--no-use-registries", "--offline"])
                assert generation["exitCode"] == 0, generation
            if name == "stale-name":
                definition = definition.replace("inputs.sdk.url", "inputs.changed.url")
            elif name == "revision":
                # The current selector must reject this before fetching it.
                definition = definition.replace(sdk_source["rev"], "0" * 40)
            elif name == "selector":
                definition = definition.replace(sdk_source["owner"], sdk_source["owner"].swapcase())
            elif name == "follows-redirect":
                definition = definition.replace('c.follows="a"', 'c.follows="b"')
            elif name == "nested-follows-redirect":
                definition = definition.replace('nixpkgs.follows="a"', 'nixpkgs.follows="b"')
            elif name == "additional-input":
                definition = definition.replace("outputs=", "inputs.extra.url="
                                                + json.dumps(sdk_ref) + ";outputs=")
            (path / "flake.nix").write_text(definition)
            if name in {"missing-node", "unreachable-node"}:
                lock = json.loads((path / "flake.lock").read_text())
                node = lock["nodes"][lock["root"]]["inputs"]["sdk"]
                if name == "missing-node":
                    del lock["nodes"][node]
                else:
                    lock["nodes"]["unused"] = copy.deepcopy(lock["nodes"][node])
                (path / "flake.lock").write_text(json.dumps(lock))
            source = {"type": "path", "path": str(path), "narHash": nar(path)}
            case = {"source": source, "reference": "path:" + str(path)
                    + "?narHash=" + source["narHash"]}
            (snapshot / (name + ".json")).write_text(json.dumps(case))
            cases.append((name, name in {"no-inputs", "root-follows", "diamond",
                                         "flake-false", "nested-override"}))
        (snapshot / "check.nix").write_text('''{ caseFile, librarySource }:
let c=builtins.fromJSON(builtins.readFile caseFile);tree=builtins.fetchTree c.source;
flake=builtins.getFlake c.reference;lib=import((builtins.fetchTree librarySource).outPath+"/lib");
lockPath=tree.outPath+"/flake.lock";
in if builtins.pathExists lockPath then import ./jvm-sdk-source-graph.nix {inherit lib;}
{inherit flake;source=c.source;lock=builtins.fromJSON(builtins.readFile lockPath);}
else assert builtins.attrNames(flake.inputs or {})==[];true
''')
        snapshot_hash = nar(snapshot)
        report["snapshotNarHash"] = snapshot_hash
        for name, accepted in cases:
            expression = ('let source=builtins.fetchTree {type="path";path='
                          + json.dumps(str(snapshot)) + ';narHash=' + json.dumps(snapshot_hash)
                          + ';};in import(source.outPath+"/check.nix") {caseFile=source.outPath+"/'
                          + name + '.json";librarySource=builtins.fromJSON '
                          + json.dumps(json.dumps(sdk_source)) + ';}')
            result = command(["nix", "eval", "--json", "--expr", expression, "--offline",
                              "--option", "pure-eval", "true",
                              "--option", "allow-import-from-derivation", "false"])
            result.update(case=name, expected="accept" if accepted else "reject")
            report["cases"].append(result)
            assert (result["exitCode"] == 0) == accepted, result
    report["status"] = "passed"
finally:
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
print("DIRECT NIX SDK REPLAY GRAPHS VERIFIED")
