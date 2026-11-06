# SPDX-License-Identifier: MIT
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

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
