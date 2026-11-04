# SPDX-License-Identifier: MIT
import importlib.util
import json
from pathlib import Path
import tempfile
import struct
import unittest
import zipfile

spec = importlib.util.spec_from_file_location('cross_type', Path(__file__).parents[1] / 'tools/cross_type.py')
projector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(projector)


class CrossType(unittest.TestCase):
    def test_json_preserves_bytes_and_rejects_nonstandard_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = dict(producer=tmp, producerIdentity='hash', files={'default': 'value.json'})
            value = root / 'value.json'
            value.write_bytes(b'{"answer": 42}\n')
            projector.data(spec, root / 'good', root / 'metadata')
            self.assertEqual((root / 'good/value.json').read_bytes(), value.read_bytes())
            for index, contents in enumerate(('not json', '{"answer": NaN}', '{"answer": Infinity}')):
                value.write_text(contents)
                with self.assertRaises(ValueError):
                    projector.data(spec, root / f'bad{index}', root / f'meta{index}')

    def test_webjar_deterministic_and_rejects_escaping_links(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            assets = root / 'assets'
            assets.mkdir()
            (assets / 'proof.js').write_text('42')
            spec = dict(assets=str(assets), groupId='org.webjars.npm', artifactId='proof', version='1.0.0')
            for output in ('a', 'b'):
                projector.webjar(spec, root / output)
            a = next((root / 'a').rglob('*.jar'))
            self.assertEqual(a.read_bytes(), next((root / 'b').rglob('*.jar')).read_bytes())
            with zipfile.ZipFile(a) as archive:
                self.assertEqual(archive.read('META-INF/resources/webjars/proof/1.0.0/proof.js'), b'42')
            (root / 'outside').write_text('outside')
            (assets / 'bad.js').symlink_to(root / 'outside')
            with self.assertRaisesRegex(ValueError, 'escapes'):
                projector.webjar(spec, root / 'bad')

    def test_native_missing_and_traversing_paths_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = dict(producer=tmp, producerIdentity='hash', system='x86_64-linux')
            for path in ('../escape.so', '/absolute.so', 'missing.so'):
                with self.assertRaises(ValueError):
                    projector.native(dict(spec, libraries={'proof': path}), root / 'output')

    def test_native_catalog_preserves_declared_target_and_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            header = bytearray(64)
            header[:6] = b'\x7fELF\x02\x01'
            struct.pack_into('<HH', header, 16, 3, 183)
            (root / 'libproof.so').write_bytes(header)
            projector.native(dict(producer=tmp, producerIdentity='hash', system='aarch64-linux',
                                  libraries={'proof': 'libproof.so'}), root / 'output')
            catalog = json.loads((root / 'output/catalog.json').read_text())
            self.assertEqual(catalog['system'], 'aarch64-linux')
            self.assertEqual(catalog['libraries']['proof'], str(root / 'libproof.so'))

    def test_wrong_system_or_binary_abi_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            library = root / 'libproof.so'
            header = bytearray(64)
            header[:6] = b'\x7fELF\x02\x01'
            struct.pack_into('<HH', header, 16, 3, 62)
            library.write_bytes(header)
            spec = dict(producer=tmp, producerIdentity='hash', libraries={'proof': 'libproof.so'})
            for system in ('aarch64-linux', 'x86_64-darwin', 'unsupported-system'):
                with self.assertRaises(ValueError):
                    projector.native(dict(spec, system=system), root / system)
            struct.pack_into('<H', header, 16, 2)  # Executable, not a shared object.
            library.write_bytes(header)
            with self.assertRaisesRegex(ValueError, 'binary ABI'):
                projector.native(dict(spec, system='x86_64-linux'), root / 'executable')


if __name__ == '__main__':
    unittest.main()
