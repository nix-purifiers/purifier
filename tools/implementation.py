#!/usr/bin/env python3
"""Stable bootstrap for project-owned purifier implementation pins.

Only this envelope is interpreted before handing off to the pinned program.
The selected implementation remains responsible for its dependency lock schema.
No shell expressions or executable paths are taken from a project lock.
"""
import argparse
from contextlib import ExitStack
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit


def validate_source(value):
    if not isinstance(value, dict):
        raise ValueError("implementation source must be an object")
    if value.get("type") == "github":
        if set(value) != {"type", "owner", "repo", "rev", "narHash"}:
            raise ValueError("invalid GitHub implementation source fields")
        for key in ("owner", "repo"):
            if not isinstance(value[key], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", value[key]):
                raise ValueError("invalid implementation source " + key)
    elif value.get("type") == "git":
        if set(value) != {"type", "url", "rev", "narHash"} or not isinstance(value["url"], str):
            raise ValueError("invalid Git implementation source fields")
        url = urlsplit(value["url"])
        if (url.scheme not in ("https", "ssh", "file") or url.query or url.fragment
                or any(ord(c) < 32 for c in value["url"])
                or not url.path.startswith("/") or (url.scheme != "file" and not url.hostname)):
            raise ValueError("Git implementation source requires an absolute https, ssh or file URL")
    else:
        raise ValueError("bootstrap version 1 requires a GitHub or Git source")
    if not isinstance(value["rev"], str) or not re.fullmatch(r"[0-9a-f]{40}", value["rev"]):
        raise ValueError("implementation source requires an immutable 40-digit revision")
    try:
        digest = base64.b64decode(value["narHash"].removeprefix("sha256-"), validate=True)
    except (ValueError, AttributeError) as error:
        raise ValueError("implementation source requires a SHA-256 NAR hash") from error
    if not value["narHash"].startswith("sha256-") or len(digest) != 32:
        raise ValueError("implementation source requires a SHA-256 NAR hash")
    return value


def validate_pin(value, tool):
    if not isinstance(value, dict) or set(value) != {"version", "tool", "source"}:
        raise ValueError("invalid implementation pin envelope")
    if type(value["version"]) is not int or value["version"] != 1:
        raise ValueError("unsupported implementation pin version; update the installed wrapper")
    if value["tool"] != tool:
        raise ValueError("implementation pin belongs to another purifier")
    validate_source(value["source"])
    return value


def same_source(left, right):
    if right is None:
        return False
    validate_source(left)
    validate_source(right)
    # A mirror/transport is a locator, not a different implementation.
    return all(left[key] == right[key] for key in ("rev", "narHash"))


def read_lock(text, checksum):
    def unique_fields(fields):
        result = {}
        for key, item in fields:
            if key in result:
                raise ValueError("duplicate JSON field in purifier lock: " + key)
            result[key] = item
        return result

    def invalid_constant(name):
        raise ValueError("invalid JSON constant in purifier lock: " + name)

    value = json.loads(text, object_pairs_hook=unique_fields, parse_constant=invalid_constant)
    if not isinstance(value, dict):
        raise ValueError("purifier lock must be an object")
    if checksum == "npm":
        stored = value.get("hash", "")
        if not isinstance(stored, str) or not stored:
            raise ValueError("purifier lock has no content hash")
        blank, count = re.subn(r'^  "hash": "' + re.escape(stored) + r'"(,?)$',
                              r'  "hash": ""\1', text, count=1, flags=re.M)
        actual = "sha256-" + base64.b64encode(hashlib.sha256(blank.encode()).digest()).decode()
    elif checksum == "sbt":
        stored = value.get("contentHash", "")
        if not re.match(r'^\{\n  "version": [0-9]+,\n  "contentHash": "[0-9a-f]{64}",\n', text):
            raise ValueError("purifier lock does not have the native sbt checksum header")
        blank, count = re.subn(r'^  "contentHash": "[0-9a-f]{64}",\n', "", text, count=1, flags=re.M)
        actual = hashlib.sha256(blank.encode()).hexdigest()
    else:
        raise ValueError("unsupported purifier checksum adapter")
    if count != 1 or stored != actual:
        raise ValueError("purifier lock content hash does not match; restore or explicitly relock it")
    return value


def render_lock(value, checksum):
    value = dict(value)
    if isinstance(value.get("implementation"), dict) and isinstance(value["implementation"].get("source"), dict):
        envelope = dict(value["implementation"])
        envelope["source"] = dict(sorted(envelope["source"].items()))
        value["implementation"] = envelope
    if checksum == "npm":
        value["hash"] = ""
        text = json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        digest = "sha256-" + base64.b64encode(hashlib.sha256(text.encode()).digest()).decode()
        return re.sub(r'^  "hash": ""(,?)$', lambda match: '  "hash": "' + digest + '"' + match[1],
                      text, count=1, flags=re.M)
    if checksum == "sbt":
        value.pop("contentHash", None)
        value = {"version": value.pop("version"), **value}
        text = json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        digest = hashlib.sha256(text.encode()).hexdigest()
        lines = text.splitlines(keepends=True)
        lines.insert(2, '  "contentHash": "' + digest + '",\n')
        return "".join(lines)
    raise ValueError("unsupported purifier checksum adapter")


def update_lock(path, pin, config):
    original = path.read_bytes()
    value = read_lock(original.decode(), config["checksum"])
    if value.get("version") not in config["lockVersions"]:
        raise ValueError("target implementation cannot migrate this lock format; lock was left unchanged")
    value["implementation"] = pin
    rendered = render_lock(value, config["checksum"])
    # Validate before replacing, and refuse to overwrite another writer.
    read_lock(rendered, config["checksum"])
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + ".", delete=False) as output:
        temporary = Path(output.name)
        try:
            output.write(rendered.encode())
            output.flush()
            os.fsync(output.fileno())
            temporary.chmod(path.stat().st_mode & 0o777)
            if path.read_bytes() != original:
                raise ValueError("purifier lock changed during implementation update; retry")
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def migrate_lock(path, pin, config, program, native_lock=None):
    """Let the selected implementation relock a staged copy before committing."""
    original = path.read_bytes()
    native = Path(native_lock) if native_lock else None
    native_original = native.read_bytes() if native else None
    with ExitStack() as cleanup:
        def stage(contents, parent, prefix):
            work = cleanup.enter_context(tempfile.NamedTemporaryFile(dir=parent, prefix=prefix, suffix=".json", delete=False))
            staged_path = Path(work.name)
            cleanup.callback(staged_path.unlink, missing_ok=True)
            staged_path.write_bytes(contents)
            return staged_path

        staged = stage(original, path.parent, ".purifier-update-")
        update_lock(staged, pin, config)
        command = [str(program), "implementation-relock", "--lockfile", str(staged)]
        native_staged = None
        if native:
            native_staged = stage(native_original, native.parent, ".purifier-native-")
            native_staged.chmod(0o400)
            command += ["--implementation-native-lockfile", str(native_staged)]
        subprocess.run(command, check=True)
        result = read_lock(staged.read_text(), config["checksum"])
        if result.get("implementation") != pin:
            raise ValueError("target implementation did not preserve the selected pin")
        if native and (native_staged.read_bytes() != native_original or native.read_bytes() != native_original):
            raise ValueError("native dependency lock changed during implementation update; neither live lock was replaced")
        if path.read_bytes() != original:
            raise ValueError("purifier lock changed during implementation update; retry")
        staged.chmod(path.stat().st_mode & 0o777)
        os.replace(staged, path)


def source_ref(source):
    validate_source(source)
    if source["type"] == "git":
        return "git+" + source["url"] + "?rev=" + source["rev"]
    return "github:" + source["owner"] + "/" + source["repo"] + "/" + source["rev"]


def nix_string(value):
    # JSON string quoting is almost Nix quoting; interpolation must also be
    # escaped. User URLs are data, never part of a Nix expression.
    return json.dumps(value, ensure_ascii=False).replace("${", r"\${")


def resolve_package(pin, config, entry, lockfile):
    if entry not in (config["tool"], config["nativeCommand"]):
        raise ValueError("unknown purifier entrypoint")
    reference = source_ref(pin["source"])
    # Git flake URLs do not consistently treat a narHash query as a fetcher
    # attribute. Check the structured fetch BEFORE evaluating package code.
    expression = ("let verified = builtins.fetchTree (builtins.fromJSON "
                  + nix_string(json.dumps(pin["source"])) + "); "
                  + "flake = builtins.getFlake " + nix_string(reference) + "; "
                  + "in builtins.seq verified.outPath flake.packages."
                  + nix_string(config["system"]) + "." + nix_string(entry))
    key = hashlib.sha256(json.dumps(pin, sort_keys=True).encode()).hexdigest()
    gc_root = Path(str(lockfile) + ".gcroots") / ("implementation-" + key + "-" + entry)
    gc_root.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(["nix", "build", "--out-link", str(gc_root.absolute()), "--print-out-paths", "--no-write-lock-file",
                             "--expr", expression], check=True, stdout=subprocess.PIPE, text=True)
    paths = result.stdout.splitlines()
    if len(paths) != 1 or not Path(paths[0]).is_absolute():
        raise ValueError("Nix did not return exactly one implementation package")
    return Path(paths[0])


def verify_package(package, pin):
    manifest = json.loads((package / "share/purifier/implementation.json").read_text())
    if (manifest.get("bootstrapVersion") != 1 or manifest.get("tool") != pin["tool"]
            or not same_source(pin["source"], manifest.get("source"))):
        raise ValueError("selected package does not confirm the pinned implementation identity")
    return manifest


def installed_pin(config):
    if config.get("source") is None:
        raise ValueError("this installation has no portable source identity; use self-update --to github:OWNER/REPO/REV")
    return validate_pin({"version": 1, "tool": config["tool"], "source": config["source"]}, config["tool"])


def run(args):
    config = json.loads(Path(args.config).read_text())
    path = Path(args.lockfile).resolve()
    if args.action == "current":
        print(json.dumps(installed_pin(config), separators=(",", ":")))
        return
    if args.action == "self-update":
        if not path.is_file():
            raise ValueError("create the project lock before updating its implementation")
        target = args.to
        if target == "installed":
            pin = installed_pin(config)
            selected = config
            program = shutil.which(args.installed_command) if args.installed_command else None
            if not program:
                raise ValueError("installed implementation command is unavailable")
        else:
            if not target.startswith(("github:", "git+https:", "git+ssh:", "git+file:")) or "#" in target:
                raise ValueError("--to requires a GitHub/Git flake reference or installed")
            metadata = json.loads(subprocess.check_output(
                ["nix", "flake", "metadata", "--refresh", "--json", "--no-write-lock-file", target], text=True))
            locked = metadata["locked"]
            keys = ("type", "owner", "repo", "rev", "narHash") if locked["type"] == "github" else ("type", "url", "rev", "narHash")
            source = {key: locked[key] for key in keys}
            pin = validate_pin({"version": 1, "tool": config["tool"], "source": source}, config["tool"])
            package = resolve_package(pin, config, config["tool"], path)
            selected = verify_package(package, pin)
            program = package / "bin" / config["tool"]
        migrate_lock(path, pin, selected, program, args.native_lockfile)
        print(config["tool"] + ": pinned implementation " + pin["source"]["rev"], file=sys.stderr)
        return
    if not path.exists():
        return  # The ecosystem wrapper owns the unlocked fallback.
    value = read_lock(path.read_text(), config["checksum"])
    pin = value.get("implementation")
    if pin is None:
        print(config["tool"] + ": warning: this legacy lock does not pin the purifier; run `"
              + config["tool"] + " self-update --to installed` to migrate it", file=sys.stderr)
        return
    validate_pin(pin, config["tool"])
    if same_source(pin["source"], config.get("source")):
        return
    # There is no environment-variable escape hatch. A selected package must
    # identify itself; its own bootstrap then sees an exact identity match.
    package = resolve_package(pin, config, args.entry, path)
    verify_package(package, pin)
    program = package / "bin" / args.entry
    if not program.is_file() or not os.access(program, os.X_OK):
        raise ValueError("selected implementation entrypoint is not executable")
    # The calling shell execs this path, so neither a successful child nor a
    # nonzero child can fall through into the originally installed wrapper.
    print(program)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("dispatch", "current", "self-update"))
    parser.add_argument("--config", required=True)
    parser.add_argument("--lockfile", required=True)
    parser.add_argument("--entry")
    parser.add_argument("--to", default="installed")
    parser.add_argument("--installed-command")
    parser.add_argument("--native-lockfile")
    args = parser.parse_args()
    try:
        run(args)
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        print("purifier: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
