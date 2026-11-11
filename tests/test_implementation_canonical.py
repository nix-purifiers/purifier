"""Checksum interoperability only; this is not PNPM implementation adoption."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location(
    "implementation", Path(__file__).parents[1] / "tools/implementation.py")
implementation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(implementation)
STYLE = "canonical-json-sha256"


class CanonicalTests(unittest.TestCase):
    def native_hash(self, value):
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8") as data:
            json.dump(value, data, ensure_ascii=False)
            data.flush()
            return subprocess.check_output([
                "node", "--input-type=module", "-e",
                'import fs from "node:fs"; import {pathToFileURL} from "node:url"; '
                'const m=await import(pathToFileURL(process.argv[1])); '
                'console.log(m.contentHash(JSON.parse(fs.readFileSync(process.argv[2],"utf8"))));',
                os.environ["PNPM_NATIVE"], data.name,
            ], text=True).strip()

    def fixture(self):
        return json.loads(Path(os.environ["PNPM_PREPARE"]).read_text())

    def test_existing_native_snapshots(self):
        for name in ("PNPM_PREPARE", "PNPM_SOURCES"):
            with self.subTest(name=name):
                text = Path(os.environ[name]).read_text()
                value = implementation.read_lock(text, STYLE)
                self.assertEqual(value["contentHash"], self.native_hash(value))
                self.assertEqual(implementation.read_lock(
                    implementation.render_lock(value, STYLE), STYLE), value)

    def test_pin_is_covered_and_native_formatter_is_independent(self):
        value = self.fixture()
        value["implementation"] = {"version": 1, "tool": "pnpm-purifier", "source": {
            "type": "github", "owner": "example", "repo": "unit-fixture",
            "rev": "a" * 40, "narHash": "sha256-" + "A" * 43 + "="}}
        before = copy.deepcopy(value)
        text = implementation.render_lock(value, STYLE)
        parsed = implementation.read_lock(text, STYLE)
        self.assertEqual(value, before)
        self.assertEqual(parsed["contentHash"], self.native_hash(parsed))
        self.assertEqual(implementation.read_lock(json.dumps(parsed), STYLE), parsed)
        with self.assertRaisesRegex(ValueError, "content hash"):
            implementation.read_lock(text.replace("unit-fixture", "tampered"), STYLE)

    def test_opaque_fields_and_large_snapshots(self):
        value = self.fixture()
        value["opaque"] = {"contentHash": "untouched", "unicode": "雪${literal}" * 30000}
        text = implementation.render_lock(value, STYLE)
        parsed = implementation.read_lock(text, STYLE)
        self.assertEqual(parsed["opaque"], value["opaque"])
        self.assertEqual(parsed["contentHash"], self.native_hash(parsed))

    def test_unicode_temporary_directory_is_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary) / "é space${literal}"
            directory.mkdir()
            with patch.object(tempfile, "tempdir", str(directory)):
                value = self.fixture()
                self.assertEqual(implementation.canonical_checksum(value), value["contentHash"])

    def test_atomic_update_and_version_rejection(self):
        pin = {"version": 1, "tool": "pnpm-purifier", "source": {
            "type": "github", "owner": "example", "repo": "unit-fixture",
            "rev": "a" * 40, "narHash": "sha256-" + "A" * 43 + "="}}
        with tempfile.TemporaryDirectory() as temporary:
            lock = Path(temporary) / "lock.json"
            lock.write_text(implementation.render_lock(self.fixture(), STYLE))
            original = lock.read_bytes()
            with self.assertRaises(ValueError):
                implementation.update_lock(lock, pin, {"checksum": STYLE, "lockVersions": [99]})
            self.assertEqual(lock.read_bytes(), original)
            implementation.update_lock(lock, pin, {"checksum": STYLE, "lockVersions": [2]})
            parsed = implementation.read_lock(lock.read_text(), STYLE)
            self.assertEqual(parsed["implementation"], pin)
            self.assertEqual(parsed["contentHash"], self.native_hash(parsed))


if __name__ == "__main__":
    unittest.main()
