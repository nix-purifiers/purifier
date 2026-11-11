# SPDX-License-Identifier: MIT
"""Measure an independent ordinary RubyGems SDK. No Bundler schema reuse."""

import ast
import base64
import hashlib
import json
import os
import selectors
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate SDK field")
        result[key] = value
    return result


def read(path):
    raw = Path(path).read_bytes()
    if len(raw) > 1048576:
        raise ValueError("SDK descriptor exceeds bound")
    return json.loads(raw, object_pairs_hook=unique)


def run(args, env=None, deadline_seconds=90, output_limit=8388608):
    child = subprocess.Popen(
        args,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    selector = selectors.DefaultSelector()
    output = [bytearray(), bytearray()]
    try:
        for index, stream in enumerate((child.stdout, child.stderr)):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, index)
        deadline = time.monotonic() + deadline_seconds
        while selector.get_map() or child.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError("SDK command deadline exceeded")
            for key, _ in selector.select(min(remaining, 0.05)):
                data = os.read(key.fileobj.fileno(), 65536)
                if not data:
                    selector.unregister(key.fileobj)
                    continue
                output[key.data].extend(data)
                if sum(map(len, output)) > output_limit:
                    raise ValueError("SDK output exceeds bound")
        if child.returncode:
            raise ValueError(
                "SDK command failed: " + output[1].decode(errors="replace")
            )
        return output[0].decode()
    finally:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait(timeout=5)
        selector.close()
        child.stdout.close()
        child.stderr.close()


def attest(descriptor, closure_file, nix, runtime_ruby=None):
    if (
        set(descriptor)
        != {
            "schemaVersion",
            "sdk",
            "components",
            "compiler",
            "nativeBuildDerivation",
            "compilerDerivation",
            "originalNativeBuildDerivation",
            "originalCompilerDerivation",
        }
        or type(descriptor["schemaVersion"]) is not int
        or descriptor["schemaVersion"] != 1
    ):
        raise ValueError("unsupported SDK descriptor")
    sdk = str(Path(descriptor["sdk"]).resolve(strict=True))
    paths = Path(closure_file).read_text().splitlines()
    if not 1 <= len(paths) <= 4096 or len(set(paths)) != len(paths) or sdk not in paths:
        raise ValueError("invalid SDK closure")

    def inside(path):
        return any(path == root or path.startswith(root + "/") for root in paths)

    for path in paths:
        if (
            not path.startswith("/nix/store/")
            or str(Path(path).resolve(strict=True)) != path
        ):
            raise ValueError("invalid immutable SDK path")
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("RUBY", "GEM_", "BUNDLE_", "BUNDLER_"))
        and k.lower() not in ("http_proxy", "https_proxy", "all_proxy")
    }
    with tempfile.TemporaryDirectory(prefix="ordinary-sdk-") as temporary:
        env.update(
            HOME=temporary, GEM_HOME=temporary + "/gems", GEM_PATH=temporary + "/gems"
        )
        observation = json.loads(
            run(
                [
                    runtime_ruby or sdk + "/bin/ruby",
                    os.environ.get(
                        "PURIFIER_CONSUMER_PROBE",
                        str(Path(__file__).with_name("rubygems_consumer_sdk_probe.rb")),
                    ),
                ],
                env,
            ),
            object_pairs_hook=unique,
        )
    if (
        observation["bundlerLoaded"]
        or observation["patchlevel"] is not None
        or observation["ruby"] != "1.8.2"
        or observation["abi"] != "1.8"
        or observation["platform"] != "x86_64-linux"
        or observation["rubygemsReport"]
        != {"name": "Gem::RubyGemsVersion", "value": "0.9.4"}
    ):
        raise ValueError("consumer runtime differs")
    expected = {
        "ruby": "1.8.2",
        "rubygems": "0.9.4",
        "sources": "0.0.1",
        "json": "1.1.3",
        "bundler": "0.3.1",
    }
    components = descriptor["components"]
    if (
        len(components) != 5
        or {item["name"]: item["version"] for item in components} != expected
    ):
        raise ValueError("SDK components differ")
    installed = {
        item["name"]: (item["version"], item["library"])
        for item in observation["installed"]
    }
    if len(observation["installed"]) != 3 or set(installed) != {
        "sources",
        "json",
        "bundler",
    }:
        raise ValueError("unlisted installed SDK artifacts")
    measured = []
    for item in components:
        if set(item) != {"name", "version", "archive", "library"}:
            raise ValueError("invalid SDK component fields")
        archive = str(Path(item["archive"]).resolve(strict=True))
        library = str(Path(item["library"]).resolve(strict=True))
        name = item["name"]
        if not inside(archive) or not inside(library) or not Path(archive).is_file():
            raise ValueError("component escapes SDK closure")
        observed = (
            observation["rubyLibrary"]
            if name == "ruby"
            else observation["rubygemsLibrary"]
            if name == "rubygems"
            else installed[name][1]
        )
        if library != observed or (
            name in installed and installed[name][0] != item["version"]
        ):
            raise ValueError("component library/version differs from observation")
        measured.append(
            dict(
                name=name,
                version=item["version"],
                archive=archive,
                archiveHash="sha256-"
                + base64.b64encode(
                    hashlib.sha256(Path(archive).read_bytes()).digest()
                ).decode(),
                library=library,
                libraryHash=run(
                    [
                        nix,
                        "--extra-experimental-features",
                        "nix-command",
                        "hash",
                        "path",
                        library,
                    ]
                ).strip(),
                role="incidental-unloaded-client"
                if name == "bundler"
                else "consumer-component",
            )
        )
    if not inside(observation["executable"]):
        raise ValueError("interpreter escapes SDK closure")
    for library in observation["nativeLibraries"]:
        if not inside(library["path"]) or not any(
            library["path"].startswith(item["library"] + "/")
            for item in measured
            if item["name"] == "json"
        ):
            raise ValueError("native library escapes JSON component")
    compiler = str(Path(descriptor["compiler"]).resolve(strict=True))
    if not inside(compiler):
        raise ValueError("compiler escapes measured closure")
    build_path = str(Path(descriptor["nativeBuildDerivation"]).resolve(strict=True))
    compiler_drv = str(Path(descriptor["compilerDerivation"]).resolve(strict=True))
    if not inside(build_path) or not inside(compiler_drv):
        raise ValueError("build provenance escapes measured closure")
    raw = Path(build_path).read_text()
    if len(raw) > 8388608 or not raw.startswith("Derive("):
        raise ValueError("unsupported native build provenance")
    build = ast.literal_eval(raw[len("Derive") :])
    build_env = dict(build[6])
    outputs = [row[1] for row in build[0]]
    compiler_raw = Path(compiler_drv).read_text()
    if len(compiler_raw) > 8388608 or not compiler_raw.startswith("Derive("):
        raise ValueError("unsupported compiler provenance")
    compiler_build = ast.literal_eval(compiler_raw[len("Derive") :])
    if (
        descriptor["originalCompilerDerivation"] not in dict(build[1])
        or compiler not in build_env.get("nativeBuildInputs", "").split()
        or compiler not in [row[1] for row in compiler_build[0]]
    ):
        raise ValueError("compiler is not an actual native build input")
    json_component = next(item for item in measured if item["name"] == "json")
    if not any(
        json_component["library"].startswith(path + "/") for path in outputs
    ) or json_component["archive"] not in build_env.get("buildCommand", ""):
        raise ValueError("native JSON does not join its original archive/build output")
    provenance = dict(
        derivation=build_path,
        originalDerivation=descriptor["originalNativeBuildDerivation"],
        derivationSha256=hashlib.sha256(Path(build_path).read_bytes()).hexdigest(),
        compilerDerivation=compiler_drv,
        originalCompilerDerivation=descriptor["originalCompilerDerivation"],
        compilerDerivationSha256=hashlib.sha256(
            Path(compiler_drv).read_bytes()
        ).hexdigest(),
        buildCommandSha256=hashlib.sha256(
            build_env["buildCommand"].encode()
        ).hexdigest(),
        nativeBuildInputs=build_env["nativeBuildInputs"].split(),
        outputs=outputs,
    )
    return dict(
        format="rubygems-native-consumer-sdk",
        schemaVersion=1,
        profile="ruby182-rubygems094-v1",
        sdk=sdk,
        observation=observation,
        components=sorted(measured, key=lambda item: item["name"]),
        compiler=dict(
            path=compiler,
            narHash=run(
                [
                    nix,
                    "--extra-experimental-features",
                    "nix-command",
                    "hash",
                    "path",
                    compiler,
                ]
            ).strip(),
        ),
        nativeBuild=provenance,
        closure=[
            dict(
                path=path,
                narHash=run(
                    [
                        nix,
                        "--extra-experimental-features",
                        "nix-command",
                        "hash",
                        "path",
                        path,
                    ]
                ).strip(),
            )
            for path in sorted(paths)
        ],
    )


if __name__ == "__main__":
    if len(sys.argv) == 7 and sys.argv[1] == "--verify":
        document = attest(read(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[6])
        expected = read(sys.argv[5])
        if (
            document != expected
            or Path(sys.argv[5]).read_text() != canonical(document) + "\n"
        ):
            raise ValueError(
                "executed SDK/physical provenance differs from attestation"
            )
        print("ORDINARY-SDK-VERIFIED|ruby182-rubygems094-v1")
    elif len(sys.argv) == 5:
        document = attest(read(sys.argv[1]), sys.argv[2], sys.argv[3])
        Path(sys.argv[4]).write_text(canonical(document) + "\n")
    else:
        raise SystemExit(
            "usage: rubygems_consumer_sdk.py [--verify] DESCRIPTOR CLOSURE_PATHS NIX ATTESTATION [ACTUAL_RUBY]"
        )
