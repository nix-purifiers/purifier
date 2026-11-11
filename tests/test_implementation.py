"""Bootstrap invariants; subprocess tests execute real selected entrypoints."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys
from unittest.mock import patch
from types import SimpleNamespace

spec = importlib.util.spec_from_file_location(
    "implementation", Path(__file__).parents[1] / "tools/implementation.py"
)
implementation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(implementation)


def source(revision="a"):
    return {"type": "github", "owner": "example", "repo": "purifier",
            "rev": revision * 40, "narHash": "sha256-" + "A" * 43 + "="}


class ImplementationTests(unittest.TestCase):
    def test_immutable_source_required(self):
        self.assertEqual(implementation.validate_source(source()), source())
        for field, value in [("rev", "main"), ("narHash", ""),
                             ("owner", "../other"), ("type", "path")]:
            bad = source()
            bad[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                implementation.validate_source(bad)

    def test_git_sources_are_immutable_and_url_options_cannot_be_injected(self):
        git = {"type": "git", "url": "file:///fixture/repository", "rev": "a" * 40,
               "narHash": source()["narHash"]}
        self.assertEqual(implementation.validate_source(git), git)
        self.assertTrue(implementation.source_ref(git).endswith("?rev=" + "a" * 40))
        for url in ("/relative", "https://example.com/repo?rev=main", "file:///repo#package", "https://example.com/\nrepo"):
            with self.assertRaises(ValueError):
                implementation.validate_source(dict(git, url=url))
        self.assertTrue(implementation.same_source(git, source()))
        self.assertFalse(implementation.same_source(git, source("b")))

    def test_unknown_envelope_and_wrong_project_rejected(self):
        pin = {"version": 1, "tool": "npm-purifier", "source": source()}
        implementation.validate_pin(pin, "npm-purifier")
        for bad in [dict(pin, version=2), dict(pin, tool="sbt-purifier"),
                    dict(pin, executable="arbitrary")]:
            with self.assertRaises(ValueError):
                implementation.validate_pin(bad, "npm-purifier")

    def test_npm_checksum_covers_pin_and_preserves_other_fields(self):
        value = {"version": 3, "hash": "", "git": {}, "other": [42]}
        before = copy.deepcopy(value)
        text = implementation.render_lock(value, "npm")
        parsed = implementation.read_lock(text, "npm")
        self.assertEqual(parsed["other"], [42])
        self.assertEqual(value, before)
        value["implementation"] = {"version": 1, "tool": "npm-purifier", "source": source()}
        text = implementation.render_lock(value, "npm")
        implementation.read_lock(text, "npm")
        with self.assertRaises(ValueError):
            implementation.read_lock(text.replace('"repo": "purifier"', '"repo": "different"'), "npm")

    def test_sbt_native_checksum_layout(self):
        value = {"version": 8, "sbtVersion": "1.10.0", "projects": []}
        text = implementation.render_lock(value, "sbt")
        self.assertTrue(text.startswith('{\n  "version": 8,\n  "contentHash": "'))
        self.assertEqual(implementation.read_lock(text, "sbt")["projects"], [])
        with self.assertRaises(ValueError):
            implementation.read_lock(text.replace("1.10.0", "1.11.0"), "sbt")

    def test_checksum_rendering_never_replaces_opaque_nested_fields(self):
        value = {"other": {"hash": "", "contentHash": "untouched"}, "version": 3, "hash": ""}
        result = implementation.read_lock(implementation.render_lock(value, "npm"), "npm")
        self.assertEqual(result["other"], value["other"])
        sbt = {"projects": [{"id": "example"}], "version": 3, "other": value["other"]}
        result = implementation.read_lock(implementation.render_lock(sbt, "sbt"), "sbt")
        self.assertEqual(result["projects"], sbt["projects"])
        self.assertEqual(result["other"], sbt["other"])

    def test_duplicate_json_fields_fail_before_dispatch(self):
        with self.assertRaisesRegex(ValueError, "duplicate JSON"):
            implementation.read_lock('{"version":3,"version":3}', "npm")

    def test_selected_package_must_confirm_identity(self):
        config = {"tool": "npm-purifier", "source": source(), "bootstrapVersion": 1,
                  "lockVersions": [3], "checksum": "npm", "system": "x86_64-linux"}
        pin = {"version": 1, "tool": "npm-purifier", "source": source()}
        with tempfile.TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "share/purifier/implementation.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(json.dumps(config))
            implementation.verify_package(Path(tmp), pin)
            manifest.write_text(json.dumps(dict(config, source=source("b"))))
            with self.assertRaises(ValueError):
                implementation.verify_package(Path(tmp), pin)

    def test_update_is_atomic_and_requires_supported_format(self):
        pin = {"version": 1, "tool": "npm-purifier", "source": source()}
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / "lock.json"
            original = implementation.render_lock({"version": 3, "git": {}, "hash": ""}, "npm")
            lock.write_text(original)
            with self.assertRaises(ValueError):
                implementation.update_lock(lock, pin, {"checksum": "npm", "lockVersions": [4]})
            self.assertEqual(lock.read_text(), original)
            implementation.update_lock(lock, pin, {"checksum": "npm", "lockVersions": [3]})
            parsed = implementation.read_lock(lock.read_text(), "npm")
            self.assertEqual(parsed["implementation"], pin)
            self.assertEqual(parsed["git"], {})

    def test_failed_native_migration_preserves_both_locks(self):
        pin = {"version": 1, "tool": "npm-purifier", "source": source()}
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / "lock.json"
            native = Path(tmp) / "package-lock.json"
            original = implementation.render_lock({"version": 3, "git": {}, "hash": ""}, "npm")
            lock.write_text(original)
            native.write_text("original native lock")
            program = Path(tmp) / "failing-purifier"
            program.write_text("#!" + sys.executable + "\nraise SystemExit(42)\n")
            program.chmod(0o755)
            with self.assertRaises(subprocess.CalledProcessError):
                implementation.migrate_lock(lock, pin, {"checksum": "npm", "lockVersions": [3]}, program, native)
            self.assertEqual(lock.read_text(), original)
            self.assertEqual(native.read_text(), "original native lock")
            self.assertEqual(list(Path(tmp).glob(".purifier-update-*")), [])

    def test_concurrent_writer_is_never_rolled_back(self):
        pin = {"version": 1, "tool": "npm-purifier", "source": source()}
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / "lock.json"
            native = Path(tmp) / "package-lock.json"
            lock.write_text(implementation.render_lock({"version": 3, "hash": "", "git": {}}, "npm"))
            native.write_text("pair A")
            program = Path(tmp) / "concurrent-writer"
            program.write_text("#!" + sys.executable + "\nfrom pathlib import Path\n"
                               + "Path(" + repr(str(native)) + ").write_text('pair B')\n"
                               + "Path(" + repr(str(lock)) + ").write_text('pair B')\n")
            program.chmod(0o755)
            with self.assertRaisesRegex(ValueError, "changed during"):
                implementation.migrate_lock(lock, pin, {"checksum": "npm", "lockVersions": [3]}, program, native)
            self.assertEqual(native.read_text(), "pair B")
            self.assertEqual(lock.read_text(), "pair B")
            self.assertEqual(list(Path(tmp).glob(".purifier-*-*")), [])

    def test_failed_preflight_leaves_no_staged_locks(self):
        pin = {"version": 1, "tool": "npm-purifier", "source": source()}
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / "lock.json"
            lock.write_text(implementation.render_lock({"version": 3, "hash": ""}, "npm"))
            with self.assertRaises(ValueError):
                implementation.migrate_lock(lock, pin, {"checksum": "npm", "lockVersions": [4]}, "/never-run")
            self.assertEqual(list(Path(tmp).glob(".purifier-update-*")), [])

    def test_successful_native_migration_preserves_selected_pin(self):
        pin = {"version": 1, "tool": "npm-purifier", "source": source()}
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / "lock.json"
            lock.write_text(implementation.render_lock({"version": 3, "git": {}, "hash": ""}, "npm"))
            program = Path(tmp) / "purifier"
            program.write_text("#!" + sys.executable + "\nimport sys\nassert sys.argv[1:3] == ['implementation-relock', '--lockfile']\n")
            program.chmod(0o755)
            implementation.migrate_lock(lock, pin, {"checksum": "npm", "lockVersions": [3]}, program)
            self.assertEqual(implementation.read_lock(lock.read_text(), "npm")["implementation"], pin)
            self.assertEqual(list(Path(tmp).glob(".purifier-update-*")), [])

    def test_native_stage_is_private_and_original_is_untouched(self):
        pin = {"version": 1, "tool": "npm-purifier", "source": source()}
        with tempfile.TemporaryDirectory() as tmp:
            lock = Path(tmp) / "lock.json"
            native = Path(tmp) / "package-lock.json"
            native.write_text("private dependency lock")
            native.chmod(0o600)
            lock.write_text(implementation.render_lock({"version": 3, "hash": ""}, "npm"))
            program = Path(tmp) / "purifier"
            program.write_text("#!" + sys.executable + "\nfrom pathlib import Path\nimport sys\n"
                               + "p=Path(sys.argv[-1])\nassert sys.argv[-2]=='--implementation-native-lockfile'\n"
                               + "assert p.stat().st_mode & 0o777 == 0o400\n"
                               + "assert p.read_text()=='private dependency lock'\n")
            program.chmod(0o755)
            implementation.migrate_lock(lock, pin, {"checksum": "npm", "lockVersions": [3]}, program, native)
            self.assertEqual(native.read_text(), "private dependency lock")
            self.assertEqual(native.stat().st_mode & 0o777, 0o600)

    def test_installed_update_cannot_change_pinned_dispatch(self):
        # Unit boundary: Nix source/package resolution is replaced here. The
        # selected package, manifest, checksum and emitted executable are real.
        pin = {"version": 1, "tool": "npm-purifier", "source": source("a")}
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            package = directory / "selected"
            (package / "bin").mkdir(parents=True)
            (package / "bin/npm").write_text("#!" + sys.executable + "\nprint(42)\n")
            (package / "bin/npm").chmod(0o755)
            config = {"tool": "npm-purifier", "nativeCommand": "npm", "source": source("b"),
                      "bootstrapVersion": 1, "checksum": "npm", "lockVersions": [3], "system": "x86_64-linux"}
            manifest = package / "share/purifier/implementation.json"
            manifest.parent.mkdir(parents=True)
            manifest.write_text(json.dumps(dict(config, source=source("a"))))
            installed = directory / "installed.json"
            installed.write_text(json.dumps(config))
            lock = directory / "lock.json"
            lock.write_text(implementation.render_lock({"version": 3, "hash": "", "implementation": pin}, "npm"))
            args = SimpleNamespace(config=installed, lockfile=lock, action="dispatch", entry="npm")
            from io import StringIO
            output = StringIO()
            with patch.object(implementation, "resolve_package", return_value=package) as resolve, patch("sys.stdout", output):
                implementation.run(args)
            self.assertEqual(output.getvalue().strip(), str(package / "bin/npm"))
            self.assertEqual(resolve.call_args.args[0], pin)
            self.assertEqual(subprocess.check_output([output.getvalue().strip()], text=True), "42\n")


if __name__ == "__main__":
    unittest.main()
