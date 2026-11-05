# SPDX-License-Identifier: MIT
"""Reject ambiguous or escaping resource bundles before publishing them."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

module = importlib.util.spec_from_file_location('resource_projection', Path(__file__).parents[1] / 'tools/resource_projection.py')
resources = importlib.util.module_from_spec(module)
module.loader.exec_module(resources)


class ResourceTests(unittest.TestCase):
    def test_invalid_selections_and_dependency_collisions(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            producer = root / 'producer'
            producer.mkdir()
            (producer / 'public').mkdir()
            (producer / 'public/a.proto').write_text('syntax = "proto3";')
            (root / 'secret').write_text('private')
            spec = {'producer': str(producer), 'producerIdentity': 'fixture',
                    'roots': {'a.proto': 'public/a.proto'}}
            for prefix in ('../escape', '/escape', 'a/../escape', './escape', 'a\\b'):
                with self.subTest(prefix=prefix), self.assertRaises(ValueError):
                    resources.project(dict(spec, roots={prefix: 'public/a.proto'}), root / 'bad')
            (producer / 'public/escape').symlink_to(root / 'secret')
            with self.assertRaisesRegex(ValueError, 'escapes'):
                resources.project(dict(spec, roots={'.': 'public'}), root / 'escape')
            (producer / 'public/escape').unlink()
            bundle = root / 'bundle'
            resources.project(spec, bundle)
            with self.assertRaisesRegex(ValueError, 'collision'):
                resources.project(dict(spec, dependencies=[{'path': str(bundle), 'identity': 'fixture'}]), root / 'collision')
            with self.assertRaisesRegex(ValueError, 'absent'):
                resources.project(dict(spec, schema={'format': 'thrift', 'entrypoints': ['missing.thrift']}), root / 'missing')
            (bundle / 'files/a.proto').write_text('changed')
            with self.assertRaisesRegex(ValueError, 'digest'):
                resources.project(dict(spec, roots={'other.proto': 'public/a.proto'},
                                       dependencies=[{'path': str(bundle), 'identity': 'fixture'}]), root / 'digest')

    def test_reproducible_bytes_and_changed_producer(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            producer = root / 'producer'
            producer.mkdir()
            (producer / 'public').mkdir()
            spec = {'producer': str(producer), 'producerIdentity': 'fixture', 'roots': {'.': 'public'}}
            archives = []
            for index, value in enumerate((42, 43, 42)):
                (producer / 'public/value.json').write_text(json.dumps({'value': value}))
                destination = root / str(index)
                resources.project(spec, destination)
                archives.append((destination / 'resources.jar').read_bytes())
            self.assertEqual(archives[0], archives[2])
            self.assertNotEqual(archives[0], archives[1])


if __name__ == '__main__':
    unittest.main()
