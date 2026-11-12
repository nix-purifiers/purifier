# SPDX-License-Identifier: MIT
"""Opt-in test packaging policy; original runtime/compiler inputs remain explicit."""
from pathlib import Path
import hashlib
import importlib.util
import json
import os
import re
import shlex
import sys

mode, role, inventory, helper, runtime, record = sys.argv[1:]
runtime, record = Path(runtime), Path(record)
module = importlib.util.spec_from_file_location('bounded', helper)
bounded = importlib.util.module_from_spec(module)
module.loader.exec_module(bounded)
sha = lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()

if mode == 'ruby-link':
    expected = json.loads(Path(inventory).read_text())[role]
    result = {}
    for extension, objects in expected.items():
        directory = Path.cwd() / 'ext' / extension
        makefile = directory / 'Makefile'
        original = makefile.read_bytes()
        line = next(line for line in original.decode().splitlines() if line.startswith('OBJS ='))
        actual = shlex.split(line.split('=', 1)[1])
        assert sorted(actual) == objects and len(actual) == len(set(actual))
        assert all(re.fullmatch(r'[A-Za-z0-9_+.-]+\.o', name) for name in objects)
        before = {name: sha(directory / name) for name in objects}
        target = directory / (extension + '.so')
        target.unlink()
        command = ['make', '-C', str(directory), 'OBJS=' + ' '.join(objects), extension + '.so']
        process = bounded.run(command, timeout=90)
        sys.stdout.buffer.write(process.stdout)
        sys.stderr.buffer.write(process.stderr)
        assert process.returncode == 0
        clean = re.sub(rb'\x1b\[[0-9;]*[A-Za-z]', b'', process.stdout).decode()
        links = [line for line in clean.splitlines() if line.startswith('gcc -shared')]
        assert len(links) == 1
        assert [part for part in shlex.split(links[0]) if part.endswith('.o')] == objects
        assert {name: sha(directory / name) for name in objects} == before
        assert makefile.read_bytes() == original
        result[extension] = sha(target)
    record.write_text(json.dumps(result, sort_keys=True) + '\n')
    print('RESOURCE-RECIPE-V1|' + role + '|objects unchanged; canonical links completed')
elif mode == 'ruby-install':
    expected = json.loads(record.read_text())
    version = '1.6' if role == 'ruby160' else '1.8'
    for extension, digest in expected.items():
        installed = runtime / 'lib/ruby' / version / 'i686-linux-gnu' / (extension + '.so')
        assert sha(installed) == digest
    print('RESOURCE-RECIPE-V1|' + role + '|installation preserved canonical links')
elif mode == 'openssl-date':
    header = Path('crypto/buildinf.h')
    original = header.read_bytes()
    fixed, count = re.subn(rb'(?m)^([ \t]*#define DATE )"[^"\n]*"$',
                          lambda match: match.group(1) + b'"Thu Jan  1 00:00:00 UTC 1970"', original)
    assert count == 1
    header.write_bytes(fixed)
    Path('crypto/cversion.o').unlink()
    process = bounded.run(['make'], timeout=120)
    sys.stdout.buffer.write(process.stdout)
    sys.stderr.buffer.write(process.stderr)
    assert process.returncode == 0 and header.read_bytes() == fixed
    record.write_text(sha(header) + '\n')
    print('RESOURCE-RECIPE-V1|openssl097|explicit generated DATE=1970-01-01 UTC')
elif mode == 'openssl-install':
    assert sha(Path('crypto/buildinf.h')) == record.read_text().strip()
    print('RESOURCE-RECIPE-V1|openssl097|installation preserved generated DATE policy')
else:
    raise ValueError(mode)
