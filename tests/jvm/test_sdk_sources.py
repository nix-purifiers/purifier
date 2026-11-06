# SPDX-License-Identifier: MIT
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[2] / "tools"))
import jvm_sdk_sources


class SdkDeclarationTest(unittest.TestCase):
    def declaration(self):
        return {
            "version": 1,
            "system": "x86_64-linux",
            "sdks": [{
                "id": "manager",
                "source": {"type": "github", "owner": "example", "repo": "sdks",
                           "rev": "1" * 40, "narHash": "sha256-" + "A" * 43 + "="},
                "selectionKind": "jvm-sdk-adapter-v1",
                "attribute": ["packages", "x86_64-linux", "jdk"],
            }],
            "manager": "manager",
        }

    def test_explicit_manager_and_closed_source_grammar(self):
        valid = self.declaration()
        self.assertEqual(jvm_sdk_sources.validate_declaration(valid, "x86_64-linux"), valid)
        cases = []
        for key, value in [("version", True), ("version", 2), ("system", "aarch64-linux"),
                           ("manager", None), ("manager", ["manager"]),
                           ("manager", "missing"), ("unknown", "ignored")]:
            bad = copy.deepcopy(valid)
            bad[key] = value
            cases.append(bad)
        for key, value in [("selectionKind", "derivation-v1"),
                           ("selectionKind", "guess-from-java-major"),
                           ("attribute", []), ("attribute", [""]),
                           ("id", "../ambient"), ("unknown", True)]:
            bad = copy.deepcopy(valid)
            bad["sdks"][0][key] = value
            cases.append(bad)
        for key, value in [("type", "path"), ("rev", "main"), ("narHash", "sha256-missing"),
                           ("owner", "../example"), ("repo", "sdk?ref=main"),
                           ("unknown", "ignored")]:
            bad = copy.deepcopy(valid)
            bad["sdks"][0]["source"][key] = value
            cases.append(bad)
        duplicate = copy.deepcopy(valid)
        duplicate["sdks"].append(copy.deepcopy(duplicate["sdks"][0]))
        cases.append(duplicate)
        for bad in cases:
            with self.subTest(declaration=bad), self.assertRaises(ValueError):
                jvm_sdk_sources.validate_declaration(bad, "x86_64-linux")

    def test_source_graph_materializes_the_same_immutable_tree(self):
        source = self.declaration()["sdks"][0]["source"]
        metadata = {"locked": source, "path": "/nix/store/source", "locks": {}}
        for offline in (False, True):
            with patch.object(jvm_sdk_sources.subprocess, "check_output", side_effect=[
                    json.dumps(metadata), json.dumps({"path": metadata["path"]})]) as run, \
                    patch.object(jvm_sdk_sources, "validate_source_lock", return_value={}) as validate:
                jvm_sdk_sources.validate_source_graph(source, offline=offline)
                first, second = [call.args[0] for call in run.call_args_list]
                self.assertEqual(first[1:3], ["flake", "metadata"])
                self.assertEqual(second[1:3], ["flake", "archive"])
                self.assertEqual(first[3:], second[3:])
                self.assertIn("--no-update-lock-file", second)
                self.assertNotIn("--no-write-lock-file", second)
                self.assertIn("--no-use-registries", second)
                self.assertEqual(second[second.index("pure-eval") + 1], "true")
                self.assertEqual(second[second.index("allow-import-from-derivation") + 1], "false")
                self.assertEqual("--offline" in second, offline)
                validate.assert_called_once_with(metadata["path"], metadata["locks"])
        with patch.object(jvm_sdk_sources.subprocess, "check_output", side_effect=[
                json.dumps(metadata), json.dumps({"path": "/nix/store/other"})]), \
                patch.object(jvm_sdk_sources, "validate_source_lock") as validate:
            with self.assertRaisesRegex(ValueError, "archive differs"):
                jvm_sdk_sources.validate_source_graph(source)
            validate.assert_not_called()

    def test_missing_source_tree_is_not_an_absent_lock(self):
        with patch.object(Path, "is_dir", return_value=False):
            with self.assertRaisesRegex(ValueError, "not materialized"):
                jvm_sdk_sources.validate_source_lock(
                    "/nix/store/missing-sdk-tree", {"version": 7, "root": "root", "nodes": {"root": {}}})

    def test_duplicate_json_fields_are_not_silently_replaced(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "sdk.json"
            path.write_text('{"manager":"first","manager":"second"}')
            with self.assertRaisesRegex(ValueError, "duplicate JSON field"):
                jvm_sdk_sources.read_json(path)
            path.write_text(json.dumps(self.declaration()))
            self.assertEqual(jvm_sdk_sources.read_json(path), self.declaration())


if __name__ == "__main__":
    unittest.main()
