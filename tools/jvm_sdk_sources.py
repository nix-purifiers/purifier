# SPDX-License-Identifier: MIT
"""Immutable JVM SDK declarations and native source-lock validation.

The Nix resolver reconstructs packages. This module never turns JSON store
paths into SDKs, refreshes a source lock, or combines no-write with no-update.
"""
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import urlencode


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field: " + key)
        result[key] = value
    return result


def read_json(path):
    return json.loads(Path(path).read_text(), object_pairs_hook=_object)


def _keys(value, keys, label):
    if not isinstance(value, dict) or set(value) != set(keys):
        raise ValueError(label + " has unknown or missing fields")


def validate_source(source):
    _keys(source, ("type", "owner", "repo", "rev", "narHash"), "SDK source")
    if source["type"] != "github":
        raise ValueError("only immutable GitHub SDK sources are supported")
    for key in ("owner", "repo"):
        if (not isinstance(source[key], str)
                or not re.fullmatch(r"[A-Za-z0-9_.-]+", source[key])
                or source[key] in {".", ".."}):
            raise ValueError("invalid GitHub " + key)
    if not isinstance(source["rev"], str) or not re.fullmatch(r"[0-9a-f]{40}", source["rev"]):
        raise ValueError("SDK source requires an immutable revision")
    if not isinstance(source["narHash"], str) or not re.fullmatch(r"sha256-[A-Za-z0-9+/]{43}=", source["narHash"]):
        raise ValueError("SDK source requires a SHA256 NAR hash")


def validate_declaration(value, system):
    _keys(value, ("version", "system", "sdks", "manager"), "SDK declaration")
    if type(value["version"]) is not int or value["version"] != 1:
        raise ValueError("unsupported SDK declaration version")
    if value["system"] != system or system != "x86_64-linux":
        raise ValueError("explicit SDK declaration requires the supported execution system")
    if not isinstance(value["sdks"], list) or not value["sdks"]:
        raise ValueError("SDK declaration needs SDK selections")
    ids = set()
    for selection in value["sdks"]:
        _keys(selection, ("id", "source", "selectionKind", "attribute"), "SDK selection")
        sdk_id = selection["id"]
        if not isinstance(sdk_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", sdk_id) or sdk_id in ids:
            raise ValueError("SDK ids must be valid and unique")
        ids.add(sdk_id)
        validate_source(selection["source"])
        if selection["selectionKind"] not in ("derivation-v1", "jvm-sdk-adapter-v1"):
            raise ValueError("unsupported SDK selection kind")
        if (not isinstance(selection["attribute"], list) or not selection["attribute"]
                or not all(isinstance(key, str) and key for key in selection["attribute"])):
            raise ValueError("SDK attribute must be a nonempty string path")
    if not isinstance(value["manager"], str) or value["manager"] not in ids:
        raise ValueError("explicit SDK declaration needs exactly one known manager")
    manager = next(s for s in value["sdks"] if s["id"] == value["manager"])
    if manager["selectionKind"] != "jvm-sdk-adapter-v1":
        raise ValueError("manager selection requires an explicit source-owned adapter")
    return value


def validate_source_graph(source, *, offline=False, nix="nix"):
    """Acquire/inspect an immutable source without updating its native lock."""
    validate_source(source)
    reference = ("github:" + source["owner"] + "/" + source["repo"] + "/" + source["rev"]
                 + "?" + urlencode({"narHash": source["narHash"]}))
    command = [nix, "flake", "metadata", reference, "--json", "--no-update-lock-file",
               "--no-use-registries", "--option", "pure-eval", "true",
               "--option", "allow-import-from-derivation", "false"]
    if offline:
        command.append("--offline")
    metadata = json.loads(subprocess.check_output(command, text=True), object_pairs_hook=_object)
    locked = metadata["locked"]
    if any(locked.get(key) != value for key, value in source.items()):
        raise ValueError("native SDK source identity differs")
    return {"source": source, "sourceLock": validate_source_lock(metadata["path"], metadata["locks"])}


def validate_source_lock(source_path, graph):
    """Bind a native-resolved graph to the immutable tree's original lock.

    The native resolver owns follows semantics. This stricter check cannot
    make a graph acceptable when native no-update resolution rejected it.
    """
    path = Path(source_path)
    if not str(path).startswith("/nix/store/") or path.resolve() != path:
        raise ValueError("native SDK source is not a canonical store tree")
    root = graph["root"]
    nodes = graph["nodes"]
    if graph["version"] != 7 or root not in nodes:
        raise ValueError("unsupported native SDK source lock graph")
    for name, node in nodes.items():
        if name != root:
            locked_node = dict(node.get("locked", {}))
            locked_node.pop("lastModified", None)
            validate_source(locked_node)
    lock_path = path / "flake.lock"
    if not lock_path.exists():
        if set(nodes) != {root} or nodes[root].get("inputs", {}):
            raise ValueError("SDK source without a lock must have no external inputs")
        source_lock = {"state": "absent-no-external-inputs"}
    else:
        raw = lock_path.read_bytes()
        if json.loads(raw, object_pairs_hook=_object) != graph:
            raise ValueError("native SDK graph is not bound to the source lock")
        source_lock = {"state": "present", "sha256": hashlib.sha256(raw).hexdigest()}
    return source_lock
