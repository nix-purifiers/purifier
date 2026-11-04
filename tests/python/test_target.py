# SPDX-License-Identifier: MIT
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'tools'))
from packaging.tags import sys_tags
from python_repository import interpreter_tags
from python_target import PROBE

WORKER = Path(__file__).resolve().parents[2] / 'tools/python_target.py'


class TargetTagsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.facts = json.loads(subprocess.check_output(
            [sys.executable, '-E', '-s', '-c', PROBE], cwd=WORKER.parent, text=True))

    def tags(self, facts):
        return json.loads(subprocess.check_output(
            [sys.executable, '-I', str(WORKER)], input=json.dumps(facts), text=True))

    def version(self, major, minor):
        facts = copy.deepcopy(self.facts)
        facts['version'] = [major, minor, 0, 'final', 0]
        facts['implementation'] = 'cpython'
        facts['refcount'] = False
        facts['extensionSuffixes'] = ['.so']
        facts['config'].update(py_version_nodot=str(major) + str(minor), Py_DEBUG=0,
                               Py_GIL_DISABLED=0, WITH_PYMALLOC=1, Py_UNICODE_SIZE=4)
        return facts

    def test_current_interpreter_matches_packaging_without_mutating_caller(self):
        expected = [str(tag) for tag in sys_tags()]
        self.assertEqual(interpreter_tags(sys.executable), expected)
        self.assertEqual([str(tag) for tag in sys_tags()], expected)

    def test_historical_cpython_abi_facts_are_not_replaced_by_helper_version(self):
        for version, abi in [((2, 7), 'cp27mu'), ((3, 7), 'cp37m'), ((3, 8), 'cp38')]:
            with self.subTest(version=version):
                tags = self.tags(self.version(*version))
                prefix = 'cp' + ''.join(map(str, version)) + '-' + abi + '-'
                self.assertTrue(tags[0].startswith(prefix), tags[:3])

    def test_debug_and_free_threaded_abi_are_preserved(self):
        debug = self.version(3, 8)
        debug['config']['Py_DEBUG'] = 1
        tags = self.tags(debug)
        self.assertTrue(tags[0].startswith('cp38-cp38d-'), tags[:3])
        self.assertTrue(any(tag.startswith('cp38-cp38-') for tag in tags))
        threaded = self.version(3, 13)
        threaded['config']['Py_GIL_DISABLED'] = 1
        self.assertTrue(self.tags(threaded)[0].startswith('cp313-cp313t-'))

    def test_target_glibc_and_manylinux_policy_are_not_taken_from_helper(self):
        if self.facts['system'] != 'Linux' or self.facts['glibc'][0] != 2:
            self.skipTest('native glibc platform assertion')
        target = self.version(3, 8)
        target['glibc'] = [2, 28]
        target['manylinux'] = {'flags': {'manylinux2014_compatible': False}, 'versions': {}}
        tags = self.tags(target)
        self.assertFalse(any('manylinux_2_29_' in tag for tag in tags))
        self.assertTrue(any('manylinux_2_28_' in tag for tag in tags))
        self.assertFalse(any('manylinux_2_17_' in tag for tag in tags))
        self.assertFalse(any('manylinux2014_' in tag for tag in tags))
        self.assertTrue(any('manylinux_2_27_' in tag for tag in tags))

    def test_target_manylinux_callback_preserves_none_and_explicit_veto(self):
        if self.facts['system'] != 'Linux' or self.facts['glibc'][0] != 2:
            self.skipTest('native glibc platform assertion')
        target = self.version(3, 8)
        target['glibc'] = [2, 28]
        arch = target['platform'].replace('-', '_').replace('.', '_')[len('linux_'):]
        archs = ['armv8l', 'armv7l'] if arch == 'armv8l' else [arch]
        target['manylinux'] = {'flags': {}, 'callback': True, 'versions': {
            f'2.{minor}.{value}': False if minor == 27 else None
            for value in archs for minor in range(29)
        }}
        tags = self.tags(target)
        self.assertTrue(any('manylinux_2_28_' in tag for tag in tags))
        self.assertFalse(any('manylinux_2_27_' in tag for tag in tags))
        self.assertTrue(any('manylinux_2_26_' in tag for tag in tags))

    def test_target_pointer_width_controls_linux_architecture(self):
        if self.facts['system'] != 'Linux':
            self.skipTest('Linux platform assertion')
        target = self.version(3, 8)
        target.update(platform='linux-x86_64', pointerBytes=4)
        tags = self.tags(target)
        self.assertTrue(any(tag.endswith('-linux_i686') for tag in tags))
        self.assertFalse(any(tag.endswith('-linux_x86_64') for tag in tags))


if __name__ == '__main__':
    unittest.main()
