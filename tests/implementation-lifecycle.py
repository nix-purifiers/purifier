#!/usr/bin/env python3
"""Real Nix/Git bootstrap lifecycle, run outside the build sandbox by CI.

The fixtures are intentionally small purifier implementations, not an sbt/npm
support claim. No resolver, Nix command, source identity or package is mocked.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

sys.dont_write_bytecode = True

ENTRY = r'''
import argparse, contextlib, importlib.util, io, json, os, sys
from pathlib import Path
sys.dont_write_bytecode = True
spec=importlib.util.spec_from_file_location("bootstrap", @BOOTSTRAP@)
bootstrap=importlib.util.module_from_spec(spec)
spec.loader.exec_module(bootstrap)
config=Path(__file__).parent.parent/"share/purifier/implementation.json"
manifest=json.loads(config.read_text())
parser=argparse.ArgumentParser()
parser.add_argument("command", nargs="?", default="native")
parser.add_argument("--lockfile", default=str(Path.cwd()/"fixture-purifier.lock.json"))
parser.add_argument("--implementation-native-lockfile")
parser.add_argument("--to", default="installed")
parser.add_argument("--exit", type=int, default=0)
args, rest=parser.parse_known_args()
args.config=str(config)
args.entry=Path(__file__).name
if args.command=="self-update":
    args.action="self-update"
    args.installed_command=str(Path(__file__).absolute())
    args.native_lockfile=str(Path.cwd()/"native.json")
    bootstrap.run(args)
else:
    args.action="dispatch"
    output=io.StringIO()
    with contextlib.redirect_stdout(output): bootstrap.run(args)
    selected=output.getvalue().strip()
    if selected: os.execv(selected,[selected,*sys.argv[1:]])
    if args.command=="implementation-relock":
        assert Path(args.implementation_native_lockfile).read_bytes()==(Path.cwd()/"native.json").read_bytes()
        print("native relock @MARKER@",file=sys.stderr)
    else:
        print(json.dumps({"marker":@MARKER@,"source":manifest["source"],"cwd":str(Path.cwd()),"arguments":sys.argv[1:]}))
        print("native stderr @MARKER@",file=sys.stderr)
        raise SystemExit(args.exit)
'''


def command(argv, cwd=None, expected=0, env=None):
    result = subprocess.run(list(map(str, argv)), cwd=cwd, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, env=env)
    if result.returncode != expected:
        raise AssertionError(f"{argv}: exit {result.returncode}, expected {expected}\n{result.stdout}\n{result.stderr}")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap", required=True)
    parser.add_argument("--nixpkgs", required=True)
    parser.add_argument("--system", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()
    import importlib.util
    spec = importlib.util.spec_from_file_location("bootstrap", args.bootstrap)
    bootstrap = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bootstrap)
    with tempfile.TemporaryDirectory(prefix="purifier-implementation-") as tmp:
        root = Path(tmp).resolve()
        repository = root / "implementation"
        repository.mkdir()
        command(["git", "init", "-q", repository])
        command(["git", "config", "user.name", "Purifier fixture"], repository)
        command(["git", "config", "user.email", "fixture@example.invalid"], repository)
        command(["git", "config", "commit.gpgSign", "false"], repository)
        flake = '''{
          inputs.nixpkgs = { url = @NIXPKGSURL@; flake = false; };
          inputs.bootstrap = { url = @BOOTSTRAPURL@; flake = false; };
          outputs = { self, nixpkgs, bootstrap }: let
            system = @SYSTEM@;
            pkgs = import nixpkgs { inherit system; };
            manifest = pkgs.writeText "implementation.json" (builtins.toJSON {
              bootstrapVersion=1; tool="fixture-purifier"; nativeCommand="fixture";
              inherit system; checksum="npm"; lockVersions=[3];
              source={type="git";url=@URL@;rev=self.rev;narHash=self.narHash;};
            });
            entry = pkgs.writeText "entry.py" (
              "#!${pkgs.python3}/bin/python\n" +
              builtins.replaceStrings ["@BOOTSTRAP@"]
                [ (builtins.toJSON "${bootstrap}/tools/implementation.py") ]
                (builtins.readFile ./entry.py));
            package = pkgs.runCommand "fixture-implementation" {} \'\'
              mkdir -p "$out/bin" "$out/share/purifier"
              cp ${entry} "$out/bin/fixture-purifier"
              cp ${entry} "$out/bin/fixture"
              chmod +x "$out/bin/fixture" "$out/bin/fixture-purifier"
              cp ${manifest} "$out/share/purifier/implementation.json"
            \'\';
          in { packages.${system} = { fixture-purifier=package; fixture=package; }; };
        }'''
        replacements = {"@SYSTEM@": json.dumps(args.system), "@NIXPKGSURL@": json.dumps("path:" + args.nixpkgs),
                        "@BOOTSTRAPURL@": json.dumps("path:" + str(Path(args.bootstrap).parents[1])),
                        "@URL@": json.dumps(repository.as_uri())}
        for key, value in replacements.items():
            flake = flake.replace(key, value)
        (repository / "flake.nix").write_text(flake)
        packages = []
        sources = []
        for marker in (42, 43):
            (repository / "entry.py").write_text(ENTRY.replace("@MARKER@", str(marker)))
            if marker == 42:
                command(["nix", "flake", "lock", "path:" + str(repository)])
            command(["git", "add", "flake.nix", "flake.lock", "entry.py"], repository)
            command(["git", "commit", "-qm", "fixture " + str(marker)], repository)
            revision = command(["git", "rev-parse", "HEAD"], repository).stdout.strip()
            reference = "git+" + repository.as_uri() + "?rev=" + revision
            package = Path(command(["nix", "build", "--no-link", "--print-out-paths", "--no-write-lock-file",
                                    reference + "#fixture-purifier"]).stdout.strip())
            manifest = json.loads((package / "share/purifier/implementation.json").read_text())
            bootstrap.validate_source(manifest["source"])
            assert manifest["source"]["rev"] == revision
            packages.append(package)
            sources.append(manifest["source"])
        project = root / "project"
        project.mkdir()
        native = project / "native.json"
        native.write_text('{"dependency":"1.0.0"}\n')
        original_native = native.read_bytes()
        lock = project / "fixture-purifier.lock.json"
        pin = {"version": 1, "tool": "fixture-purifier", "source": sources[0]}
        lock.write_text(bootstrap.render_lock({"version": 3, "hash": "", "dependencies": {"library": "1.0.0"},
                                             "implementation": pin}, "npm"))
        original_lock = lock.read_bytes()
        # Both public CLI and native-tool entrypoints hand off through real Nix.
        selected = command([packages[1] / "bin/fixture-purifier", "identity"], project)
        assert json.loads(selected.stdout)["source"] == sources[0]
        arguments = ["native", "argument with spaces", "--exit", "17"]
        selected = command([packages[1] / "bin/fixture", *arguments], project, expected=17)
        result = json.loads(selected.stdout)
        assert result["marker"] == 42 and result["arguments"] == arguments
        assert result["cwd"] == str(project) and "native stderr 42" in selected.stderr
        assert lock.read_bytes() == original_lock
        # Explicit update runs the real selected implementation's staged relock.
        command([packages[1] / "bin/fixture-purifier", "self-update", "--to", "installed"], project)
        assert bootstrap.read_lock(lock.read_text(), "npm")["implementation"]["source"] == sources[1]
        assert json.loads(command([packages[1] / "bin/fixture", "native"], project).stdout)["marker"] == 43
        command([packages[1] / "bin/fixture-purifier", "self-update", "--to", bootstrap.source_ref(sources[0])], project)
        assert lock.read_bytes() == original_lock and native.read_bytes() == original_native
        # External lock selection works, and malformed/unknown pins cannot fall back.
        external = root / "external.json"
        external.write_bytes(original_lock)
        assert json.loads(command([packages[1] / "bin/fixture", "identity", "--lockfile", external], project).stdout)["marker"] == 42
        value = bootstrap.read_lock(original_lock.decode(), "npm")
        value["implementation"]["version"] = 999
        lock.write_text(bootstrap.render_lock(value, "npm"))
        failure = subprocess.run([str(packages[1] / "bin/fixture"), "native"], cwd=project,
                                 capture_output=True, text=True)
        assert failure.returncode != 0 and not failure.stdout and "unsupported implementation pin" in failure.stderr
        value["implementation"]["version"] = 1
        value["implementation"]["source"]["narHash"] = "sha256-AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
        lock.write_text(bootstrap.render_lock(value, "npm"))
        failure = subprocess.run([str(packages[1] / "bin/fixture"), "native"], cwd=project,
                                 capture_output=True, text=True)
        assert failure.returncode != 0 and not failure.stdout and "native stderr" not in failure.stderr
        assert "hash mismatch" in failure.stderr.lower()
        lock.write_bytes(original_lock)
        cached_environment = dict(os.environ)
        cached_environment["NIX_CONFIG"] = os.environ.get("NIX_CONFIG", "") + "\nsubstituters =\nmax-jobs = 0\n"
        cached = command([packages[1] / "bin/fixture", "identity"], project, env=cached_environment)
        assert json.loads(cached.stdout)["marker"] == 42
        roots = list(project.glob("*.gcroots/implementation-*"))
        assert roots and all(path.is_symlink() and path.exists() for path in roots)
        receipt = {"sources": sources, "packages": list(map(str, packages)),
                   "derivations": [command(["nix-store", "--query", "--deriver", package]).stdout.strip() for package in packages],
                   "lockedMarker": 42, "updatedMarker": 43, "restoredMarker": 42,
                   "originalLockSha256": hashlib.sha256(original_lock).hexdigest(),
                   "nativeLockUnchanged": True, "realNixDispatch": True,
                   "argumentsStreamsCwdExitPreserved": True, "externalLock": True,
                   "unknownPinRejected": True, "wrongNarHashRejected": True,
                   "explicitSourceUpdate": True, "cachedWithoutBuildsOrSubstituters": True,
                   "implementationGcRoots": len(roots)}
        text = json.dumps(receipt, indent=2) + "\n"
        if args.output:
            Path(args.output).write_text(text)
        print(text, end="")


if __name__ == "__main__":
    main()
