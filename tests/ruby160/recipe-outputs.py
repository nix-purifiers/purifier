# SPDX-License-Identifier: MIT
"""Retain three original immutable output trees without changing their recipes."""
from pathlib import Path
import hashlib
import ast
import re
import importlib.util
import io
import json
import os
import platform
import selectors
import stat
import subprocess
import sys
import tarfile
import time

SUFFIXES = {
    'openssl097': 'openssl-0.9.7m-resource-metadata-v1',
    'ruby180': 'ruby-1.8.0-resource-generator-v1',
    'ruby160': 'ruby-1.6.0-resource-sdk-v1',
}
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()

if sys.argv[1] != '--worker':
    descriptor, closure, helper, out = map(Path, sys.argv[1:])
    module = importlib.util.spec_from_file_location('bounded', helper)
    bounded = importlib.util.module_from_spec(module)
    module.loader.exec_module(bounded)
    bounded.run([sys.executable, '-B', __file__, '--worker', str(descriptor),
                 str(closure), str(helper), str(out)],
                deadline_seconds=90, output_limit=1048576)
    raise SystemExit(0)

descriptor, closure_file, helper, out = map(Path, sys.argv[2:])
d = json.loads(descriptor.read_text())
assert set(d) == {'outputs', 'compiler', 'stdenv', 'nix'}
assert set(d['outputs']) == {*SUFFIXES, 'currentSystem'}
assert d['outputs']['currentSystem'] == 'x86_64-linux'
# Join each narrowly named immutable root to its captured actual derivation.
EXPECTED = {}
for role, suffix in SUFFIXES.items():
    value = d['outputs'][role]
    expected = value['path']
    assert re.fullmatch(r'/nix/store/[a-z0-9]{32}-' + re.escape(suffix), expected)
    root = Path(expected)
    assert root.resolve() == root and stat.S_ISDIR(root.lstat().st_mode)
    raw = Path(value['aterm']).read_text()
    assert len(raw) <= 1048576 and raw.startswith('Derive(')
    build = ast.literal_eval(raw[len('Derive'):])
    assert build[3] == 'i686-linux'
    assert dict(build[6])['out'] == expected
    assert dict(build[6])['src'] == value['source']
    assert expected in [row[1] for row in build[0]]
    policy = json.loads((root / 'share/nix-purifiers-resource-recipe-v1.json').read_text())
    assert policy['format'] == 'nix-purifiers-resource-test-recipe'
    assert policy['recipeVersion'] == 1 and policy['role'] == role
    EXPECTED[role] = expected
out.mkdir()
deadline = time.monotonic() + 75
receipt = dict(complete=False, scope='Opt-in resource test recipes v1; original C/archive/compiler inputs, explicit object order and generated DATE policy',
               inputs=d, commands=[], roots={}, driverSha256=sha(__file__),
               helperSha256=sha(helper), maxEntries=2000, maxFileBytes=16777216,
               maxTotalFileBytes=67108864,
               host=dict(system=platform.system(), release=platform.release(),
                         machine=platform.machine(), libc=platform.libc_ver()),
               priorRunQualification='Compare these versioned recipe output NARs to sealed exact-head local evidence. Original PR27 OpenSSL byte-level cause remains unproven.')

def save():
    (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')

def remaining():
    value = deadline - time.monotonic()
    assert value > 0, 'diagnostic traversal deadline'
    return value

def run(label, args):
    args = list(map(str, args))
    child = subprocess.Popen(args, stdin=subprocess.DEVNULL,
                             stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    selector = selectors.DefaultSelector()
    output = [bytearray(), bytearray()]
    try:
        for i, stream in enumerate((child.stdout, child.stderr)):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, i)
        command_deadline = time.monotonic() + min(20, remaining())
        while selector.get_map() or child.poll() is None:
            wait = command_deadline - time.monotonic()
            assert wait > 0, 'diagnostic command/pipe deadline'
            for key, _ in selector.select(min(wait, 0.05)):
                raw = os.read(key.fileobj.fileno(), 65536)
                if raw:
                    output[key.data].extend(raw)
                    assert sum(map(len, output)) <= 1048576, 'diagnostic command output bound'
                else:
                    selector.unregister(key.fileobj)
        row = dict(label=label, argv=args, exit=child.returncode)
        for i, stream in enumerate(('stdout', 'stderr')):
            raw = bytes(output[i])
            (out / (label + '.' + stream)).write_bytes(raw)
            row[stream + 'Sha256'] = hashlib.sha256(raw).hexdigest()
        receipt['commands'].append(row)
        save()
        assert child.returncode == 0, 'diagnostic command failed: ' + label
        return bytes(output[0])
    finally:
        # Descendants inherit the worker group; the outer owned-group helper
        # kills that entire group on worker completion/failure/deadline.
        if child.poll() is None:
            child.kill()
        child.wait(timeout=5)
        selector.close()
        child.stdout.close()
        child.stderr.close()

receipt['builderEnvironment'] = {key: os.environ.get(key) for key in (
    'NIX_BUILD_CORES', 'SOURCE_DATE_EPOCH', 'TZ', 'LANG', 'LC_ALL', 'NIX_CFLAGS_COMPILE')}
if Path('/proc/cpuinfo').exists():
    cpu = Path('/proc/cpuinfo').read_text()[:1048576]
    receipt['cpu'] = {key: next((line.split(':', 1)[1].strip() for line in cpu.splitlines()
                                if line.startswith(key + '\t')), None)
                      for key in ('model name', 'flags')}
nix = Path(d['nix']) / 'bin/nix'
run('nix-version', [nix, '--version'])
receipt['nixExecutableSha256'] = sha(nix)
run('compiler-version', [Path(d['compiler']['path']) / 'bin/gcc', '--version'])
run('compiler-target', [Path(d['compiler']['path']) / 'bin/gcc', '-dumpmachine'])
openssl_version = run('openssl-version', [Path(EXPECTED['openssl097']) / 'bin/openssl', 'version', '-a'])
assert b'built on: Thu Jan  1 00:00:00 UTC 1970' in openssl_version
for role in ('ruby160', 'ruby180'):
    executable = Path(EXPECTED[role]) / 'bin/ruby'
    run(role + '-version', [executable, '-v'])
    run(role + '-config', [executable, '-rrbconfig', '-e',
        'Config::CONFIG.keys.sort.each{|k|puts k+"="+Config::CONFIG[k].to_s}'])
for role in ('compiler', 'stdenv'):
    value = d[role]
    raw = Path(value['aterm']).read_bytes()
    assert len(raw) <= 1048576
    (out / (role + '.aterm')).write_bytes(raw)
    receipt[role + 'ATermSha256'] = hashlib.sha256(raw).hexdigest()
receipt['stdenvSetupSha256'] = sha(Path(d['stdenv']['path']) / 'setup')
closure = closure_file.read_text().splitlines()
assert closure == sorted(set(closure)) and len(closure) <= 256
assert all(path.startswith('/nix/store/') and Path(path).exists() for path in closure)
assert set(EXPECTED.values()) <= set(closure)
receipt['closure'] = []
for i, path in enumerate(closure):
    nar = run('closure-%04d' % i, [nix, '--extra-experimental-features',
                                  'nix-command', 'hash', 'path', path]).decode().strip()
    receipt['closure'].append(dict(path=path, narHash=nar))
total = count = 0
with tarfile.open(out / 'original-output-bytes.tar.gz', 'w:gz', dereference=False) as archive:
    for role, root_name in EXPECTED.items():
        root = Path(root_name)
        entries = []
        pending = [root]
        while pending:
            remaining()
            p = pending.pop()
            relative = p.relative_to(root)
            assert not relative.is_absolute() and '..' not in relative.parts
            name = role if str(relative) == '.' else role + '/' + str(relative)
            s = p.lstat()
            count += 1
            assert count <= 2000
            record = dict(path=str(relative), mode=oct(stat.S_IMODE(s.st_mode)))
            member = tarfile.TarInfo(name)
            member.mode = stat.S_IMODE(s.st_mode)
            member.mtime = s.st_mtime
            if stat.S_ISREG(s.st_mode):
                assert s.st_size <= 16777216
                total += s.st_size
                assert total <= 67108864
                # O_NOFOLLOW and inode checks prevent accidentally copying a link target.
                fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW)
                with os.fdopen(fd, 'rb') as source:
                    observed = os.fstat(source.fileno())
                    assert (observed.st_dev, observed.st_ino, observed.st_size) == (s.st_dev, s.st_ino, s.st_size)
                    raw = source.read(16777217)
                assert len(raw) == s.st_size
                record.update(type='file', size=len(raw), executable=bool(s.st_mode & 0o111),
                              sha256=hashlib.sha256(raw).hexdigest())
                member.size = len(raw)
                archive.addfile(member, io.BytesIO(raw))
            elif stat.S_ISDIR(s.st_mode):
                record['type'] = 'directory'
                member.type = tarfile.DIRTYPE
                archive.addfile(member)
                pending.extend(sorted(p.iterdir(), reverse=True))
            elif stat.S_ISLNK(s.st_mode):
                record.update(type='symlink', target=os.readlink(p))
                member.type = tarfile.SYMTYPE
                member.linkname = record['target']
                archive.addfile(member)
            else:
                raise AssertionError('unexpected special file: ' + str(p))
            entries.append(record)
        assert len({row['path'] for row in entries}) == len(entries)
        value = d['outputs'][role]
        raw = Path(value['aterm']).read_bytes()
        assert len(raw) <= 1048576
        (out / (role + '.aterm')).write_bytes(raw)
        manifest = dict(root=str(root), entries=sorted(entries, key=lambda row: row['path']))
        path = out / (role + '-manifest.json')
        path.write_text(json.dumps(manifest, indent=2) + '\n')
        receipt['roots'][role] = dict(path=str(root), entries=len(entries),
            manifestSha256=sha(path), sourceSha256=sha(Path(value['source'])),
            atermSha256=hashlib.sha256(raw).hexdigest(),
            narHash=next(row['narHash'] for row in receipt['closure'] if row['path'] == str(root)))
for role, root_name in EXPECTED.items():
    final_nar = run(role + '-final-nar', [nix, '--extra-experimental-features',
                                         'nix-command', 'hash', 'path', root_name]).decode().strip()
    assert final_nar == receipt['roots'][role]['narHash'], 'immutable root changed during snapshot'
receipt.update(complete=True, totalFileBytes=total, totalEntries=count,
               archiveSha256=sha(out / 'original-output-bytes.tar.gz'),
               symlinks='Recorded original targets; never followed during traversal')
(out / 'descriptor.json').write_bytes(descriptor.read_bytes())
(out / 'closure-paths').write_bytes(closure_file.read_bytes())
save()
