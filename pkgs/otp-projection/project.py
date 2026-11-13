# SPDX-License-Identifier: MIT
"""Materialize native-inspected compiled OTP apps; retain their real inputs."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys


def require(condition, message):
    if not condition:
        raise ValueError("purifier: compiled OTP: " + message)


def safe(value):
    return isinstance(value, str) and value and "\\" not in value and all(
        ord(c) >= 32 and ord(c) != 127 for c in value
    ) and all(part not in ("", ".", "..") for part in value.split("/"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


spec_path, escript, inspector, output = sys.argv[1:]
spec = json.loads(Path(spec_path).read_text())
out = Path(output)
allowed = [Path(p).resolve(strict=True) for p in json.loads(Path(spec["closure"]).read_text())]


def declared(path):
    resolved = path.resolve(strict=True)
    require(any(resolved == p or resolved.is_relative_to(p) for p in allowed),
            "file outside declared Nix closure: " + str(path))
    return resolved


def app_files(directory, directories=None):
    def walk(path, parents):
        actual = declared(path)
        if actual.is_dir():
            require(actual not in parents, "cyclic application directory: " + str(path))
            if directories is not None:
                directories.append((path, actual))
            for child in sorted(path.iterdir()):
                yield from walk(child, parents | {actual})
        else:
            require(actual.is_file(), "unsupported non-regular app file")
            yield path, actual
    yield from walk(directory, set())


def inventory(directory):
    directories = []
    files = [dict(path=str(path.relative_to(directory)), sha256=digest(actual),
                  mode=actual.stat().st_mode & 0o777,
                  executable=bool(actual.stat().st_mode & 0o111)) for path, actual in app_files(directory, directories)]
    return dict(files=files, directories=[dict(path=str(path.relative_to(directory)),
        mode=actual.stat().st_mode & 0o777) for path, actual in directories])


roots = []
producer = Path(spec["producer"]).resolve(strict=True)
for item in spec["applications"]:
    require(safe(item["path"]) and safe(item["observation"]), "unsafe application selection")
    directory = declared(producer / item["path"])
    observation = declared(producer / item["observation"])
    require(directory.is_relative_to(producer) and observation.is_relative_to(producer),
            "application selection escapes producer")
    roots.append(dict(directory=str(directory), observation=str(observation),
                      origin=spec["producer"], originIdentity=spec["producerIdentity"], originDirectory=str(directory), root=True))

for dependency in spec["dependencies"]:
    repository = Path(dependency["repository"]).resolve(strict=True)
    catalog = json.loads(declared(Path(dependency["catalog"])).read_text())
    require(catalog.get("format") == spec["format"] and catalog.get("system") == spec["system"]
            and catalog.get("runtimeIdentity") == spec["runtimeIdentity"], "dependency runtime/format mismatch")
    for app in catalog["applications"]:
        require(safe(app["directory"]), "unsafe dependency application directory")
        directory = declared(repository / app["directory"])
        require(directory.is_relative_to(repository), "dependency application escapes its repository")
        actual_paths = {str(path.relative_to(directory)) for path, _ in app_files(directory)}
        require(actual_paths == {entry["path"] for entry in app["files"]}, "dependency application file inventory changed")
        for entry in app["files"]:
            require(safe(entry["path"]), "unsafe dependency file")
            actual = declared(directory / entry["path"])
            require(digest(actual) == entry["sha256"]
                    and bool(actual.stat().st_mode & 0o111) == entry["executable"]
                    and actual.stat().st_mode & 0o777 == entry["mode"],
                    "dependency application bytes or mode changed")
        original = declared(Path(app["originDirectory"]))
        require(inventory(original) == inventory(directory), "dependency app inventory differs from its original producer")
        require(safe(app["name"]) and digest(declared(original / "ebin" / (app["name"] + ".app"))) == app["appSHA256"],
                "dependency native app origin changed")
        roots.append(dict(directory=str(directory), observation=str(declared(Path(app["observation"]))),
                          origin=app["origin"], originIdentity=app["originIdentity"],
                          originDirectory=str(original), root=False))

for root in roots:
    root["inventoryIdentity"] = hashlib.sha256(json.dumps(inventory(Path(root["directory"])),
        sort_keys=True, separators=(",", ":")).encode()).hexdigest()
plan_input = dict(spec, applications=roots)
work = Path(os.environ["TMPDIR"])
native_input = work / "otp-input.json"
native_plan = work / "otp-plan.json"
native_input.write_text(json.dumps(plan_input))
subprocess.run([escript, inspector, "inspect", str(native_input), str(native_plan)], check=True)
model = json.loads(native_plan.read_text())
architecture, target_os = spec["system"].split("-", 1)
require(model["runtimeFacts"]["architecture"].startswith(architecture + "-")
        and model["runtimeFacts"]["os"] == target_os, "executed runtime does not match target system")
declared(Path(model["runtimeFacts"]["runtimeRoot"]))
declared(Path(model["runtimeFacts"]["compiler"]))
for app in model["applications"]:
    source = Path(app.pop("sourceDirectory"))
    app["originDirectory"] = app.get("originDirectory", str(source))
    require(declared(Path(app["compilerExecutable"])) == declared(Path(model["runtimeFacts"]["erlc"])),
            "production erlc is not the selected native compiler")
    for module in app["modules"]:
        declared(Path(module["recordedFile"]))
    require(safe(app["name"]) and safe(app["version"]), "unsafe native application coordinates")
    app["directory"] = "lib/" + app["name"] + "-" + app["version"]
    destination = out / app["directory"]
    files = []
    directories = []
    for original, actual in app_files(source, directories):
        relative = original.relative_to(source)
        data = actual.read_bytes()
        native_magic = data.startswith((b"\x7fELF", b"MZ", b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf",
                                       b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xce", b"\xca\xfe\xba\xbe"))
        require(not native_magic and not any(path.suffix.lower() in (".so", ".dll", ".dylib", ".nif", ".a", ".o") for path in (actual, original)),
                "custom native payload needs a separate ABI/loader closure contract: " + str(relative))
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(actual, target)
        executable = bool(actual.stat().st_mode & 0o111)
        target.chmod(0o755 if executable else 0o644)
        files.append(dict(path=str(relative), sha256=digest(actual), mode=actual.stat().st_mode & 0o777,
                          executable=executable))
    for original, _ in directories:
        (destination / original.relative_to(source)).mkdir(parents=True, exist_ok=True)
    app["files"] = files
    app["directories"] = [dict(path=str(path.relative_to(source)), mode=actual.stat().st_mode & 0o777)
                          for path, actual in directories]
    observation = declared(Path(app["observation"]))
    app["observationSha256"] = digest(observation)
model.update(format=spec["format"], system=spec["system"], runtimeIdentity=spec["runtimeIdentity"],
             producerIdentity=spec["producerIdentity"], identity=spec["identity"],
             projectorIdentity=spec["projectorIdentity"])
(out / "catalog.json").write_text(json.dumps(model, sort_keys=True, indent=2) + "\n")
(out / "nix-support").mkdir()
(out / "nix-support/inputs").write_text("\n".join([spec["producer"], spec["runtime"], spec["closure"]] + [
    value for dependency in spec["dependencies"] for value in (dependency["producer"], dependency["repository"])
]) + "\n")
subprocess.run([escript, inspector, "verify", str(out / "catalog.json"), str(out)], check=True)
