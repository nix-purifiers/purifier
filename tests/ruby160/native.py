# SPDX-License-Identifier: MIT
"""Original Ruby160 consumes an upstream pure parser via existing resource APIs."""
from pathlib import Path
import base64
import hashlib
import importlib.util
import json
import os
import shutil
import struct
import sys
import tarfile
import tempfile

def compiler_version_ok(raw):
    lines = raw.splitlines()
    return bool(lines) and lines[0].split()[-1:] == [b'4.8.3']


if len(sys.argv) == 4 and sys.argv[1] == '--compiler-version-control':
    assert compiler_version_ok(sys.argv[2].encode()) == (sys.argv[3] == 'accept')
    print('compiler version control passed: ' + sys.argv[3])
    raise SystemExit(0)


input_file, closure_file, helper, nix, out = map(Path, sys.argv[1:])
inputs = json.loads(input_file.read_text())
paths = {key: Path(value) for key, value in inputs.items() if key not in (
    'selectedFormat', 'producerIdentity', 'projectionIdentity')}
module = importlib.util.spec_from_file_location('bounded', helper)
bounded = importlib.util.module_from_spec(module)
module.loader.exec_module(bounded)
out.mkdir()
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
receipt = dict(complete=False, inputs=inputs, commands=[],
               scope='Ruby160 pure runtime consumption only; generator180; no Gem/Bundler/extensions',
               driverSha256=sha(__file__), boundedHelperSha256=sha(helper))

with tempfile.TemporaryDirectory(prefix='ruby160-resource-') as tmp:
    root = Path(tmp)
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('RUBY', 'GEM_', 'BUNDLE_', 'BUNDLER_'))}
    env['HOME'] = str(root / 'home')
    Path(env['HOME']).mkdir()

    def save():
        (out / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')

    def run(label, args, stdin=b'', success=True):
        args = list(map(str, args))
        wrapper = ('import subprocess,sys,json;'
                   'p=subprocess.run(sys.argv[2:],input=bytes.fromhex(sys.argv[1]),capture_output=True);'
                   'print(json.dumps(dict(exit=p.returncode,stdout=p.stdout.hex(),stderr=p.stderr.hex())))')
        result = json.loads(bounded.run(
            [sys.executable, '-B', '-c', wrapper, stdin.hex(), *args], env))
        row = dict(label=label, argv=args, exit=result['exit'],
                   stdinSha256=hashlib.sha256(stdin).hexdigest())
        (out / (label + '.stdin')).write_bytes(stdin)
        for stream in ('stdout', 'stderr'):
            data = bytes.fromhex(result[stream])
            (out / (label + '.' + stream)).write_bytes(data)
            row[stream + 'Sha256'] = hashlib.sha256(data).hexdigest()
        receipt['commands'].append(row)
        save()
        assert (result['exit'] == 0) == success, (label, bytes.fromhex(result['stderr']))
        return bytes.fromhex(result['stdout']), bytes.fromhex(result['stderr'])

    ruby = paths['runtime'] / 'bin/ruby'
    header = ruby.read_bytes()[:20]
    assert header[:6] == b'\x7fELF\x01\x01' and struct.unpack('<H', header[18:20])[0] == 3
    assert inputs['selectedFormat'] == 'resources'
    producer, projection = paths['producer'], paths['projection']
    catalog = json.loads((projection / 'catalog.json').read_text())
    assert catalog['format'] == 'purifier-resources-v1'
    assert catalog['producerIdentity'] == inputs['producerIdentity']
    assert catalog['dependencies'] == []
    assert (projection / 'nix-support/inputs').read_text().splitlines() == [str(producer)]
    assert sha(paths['raccArchive']) == '4532f638fe2868c7e1ecbd52a7345ceca9a841038fceb12be1e153ee4f082660'
    with tarfile.open(paths['raccArchive']) as archive:
        for name, row in catalog['files'].items():
            payload = projection / 'files' / name
            original = producer / (
                'packages/racc/' + name[len('generator/'):] if name.startswith('generator/') else
                'packages/raccrt/lib/' + name[len('runtime/'):] if name.startswith('runtime/') else
                'generated/' + name[len('sample/'):])
            assert payload.read_bytes() == original.read_bytes()
            assert sha(payload) == row['sha256'] and payload.stat().st_size == row['size']
            if not name.startswith('sample/'):
                member = 'racc-1.4.4-all/' + str(original.relative_to(producer))
                assert archive.extractfile(member).read() == original.read_bytes()
    readme = (producer / 'packages/racc/README.en').read_bytes()
    assert b'ruby version 1.6.x or later' in readme
    assert (producer / 'generated/generator-runtime.txt').read_text().startswith('1.8.0|2003-08-04|i686-linux-gnu')
    assert (producer / 'generated/generator.stdout').read_bytes() == b''
    assert (producer / 'generated/generator.stderr').read_bytes() == b''
    receipt['lineage'] = {name: sha(producer / name) for name in (
        'packages/racc/bin/racc', 'packages/racc/sample/calc.y',
        'packages/raccrt/lib/racc/parser.rb', 'generated/calc.rb')}
    for key, expected in (
        ('runtimeArchive', 'ps0xH74yfbXzexl1PAtQq+f4eSYSz3rExRqAJmHQcDE='),
        ('generatorArchive', 'EVxf4KFXCavRtkNRqhvtnAMNHz13ytPy8rULNwTCAfE='),
    ):
        assert hashlib.sha256(paths[key].read_bytes()).digest() == base64.b64decode(expected)
    with tarfile.open(paths['runtimeArchive']) as source:
        version_header = source.extractfile('ruby-1.6.0/version.h').read()
        assert b'"1.6.0"' in version_header and b'"2000-09-19"' in version_header
        (out / 'original160-version.h').write_bytes(version_header)
    receipt['stdenvSetupSha256'] = sha(paths['stdenv'] / 'setup')
    receipt['runtimeSha256'] = sha(ruby)
    receipt['catalogSha256'] = sha(projection / 'catalog.json')
    receipt['payloads'] = len(catalog['files'])
    for key in ('runtimeArchive', 'generatorArchive', 'raccArchive'):
        receipt[key + 'Sha256'] = sha(paths[key])
    compiler = paths['compiler'] / 'bin/gcc'
    version, _ = run('compiler-version', [compiler, '--version'])
    target, _ = run('compiler-target', [compiler, '-dumpmachine'])
    assert compiler_version_ok(version) and target.strip() == b'i686-pc-linux-gnu'
    for label, bad in [('suffix', '4.8.30'), ('prefix', '14.8.3')]:
        run('compiler-reject-' + label, [sys.executable, '-B', __file__,
            '--compiler-version-control', 'gcc (GCC) ' + bad, 'reject'])
    receipt['compilerRole'] = 'Original runtime build toolchain, not a project native extension compiler proof'
    closure = closure_file.read_text().splitlines()
    assert closure == sorted(set(closure)) and closure
    assert all(str(path) in closure for path in paths.values())
    receipt['closure'] = []
    for i, path in enumerate(closure):
        assert path.startswith('/nix/store/') and Path(path).exists()
        raw, _ = run('closure-%04d' % i, [nix, '--extra-experimental-features',
                                          'nix-command', 'hash', 'path', path])
        receipt['closure'].append(dict(path=path, narHash=raw.decode().strip()))
    exports = root / 'exports'
    shutil.copytree(projection / 'files', exports)
    for p in [exports, *exports.rglob('*')]:
        if p.is_dir():
            p.chmod(0o700)
    trace = root / 'origins.rb'
    trace.write_text('seen={};set_trace_func proc{|event,file,line,id,binding,klass|seen[file]=true if file.index(ENV["EXPECTED_ROOT"]+"/")==0};at_exit {set_trace_func nil;seen.keys.sort.each{|file|puts "ORIGIN|#{file}"}}\n')
    for label, tree in [('original', exports), ('relocated', root / 'relocated')]:
        if label == 'relocated':
            shutil.copytree(exports, tree)
            shutil.rmtree(exports)
            assert not exports.exists()
        for name, row in catalog['files'].items():
            assert sha(tree / name) == row['sha256']
        env.update(RUBYLIB=str(tree / 'runtime') + ':' + str(tree / 'generator/lib'),
                   EXPECTED_ROOT=str(tree))
        abi = ('raise unless RUBY_VERSION=="1.6.0" && RUBY_RELEASE_DATE=="2000-09-19" && ["x"].pack("p").size==4;'
               'raise if defined?(Gem) || defined?(RUBY_PATCHLEVEL);'
               'm=Enumerable.instance_methods.map{|x|x.to_s};raise if m.include?("any?") || m.include?("all?") || m.include?("inject");'
               'raise unless Racc::Parser.racc_runtime_type=="ruby";'
               'puts [RUBY_VERSION,RUBY_RELEASE_DATE,RUBY_PLATFORM,Racc::Parser::Racc_Runtime_Version,Racc::Parser.racc_runtime_type].join("|")')
        raw, _ = run(label + '-runtime', [ruby, '-rracc/parser', '-e', abi])
        assert raw.strip() == b'1.6.0|2000-09-19|i686-linux-gnu|1.4.3|ruby'
        raw, _ = run(label + '-calculator', [ruby, '-r', trace, tree / 'sample/calc.rb'], b'6*7\nQ\n')
        assert b'= 42' in raw
        assert str(tree / 'runtime/racc/parser.rb').encode() in raw
        assert str(tree / 'sample/calc.rb').encode() in raw
        if label == 'relocated':
            assert str(exports).encode() not in raw
        if label == 'original':
            _, failure = run('original160-generator-failure', [ruby, tree / 'generator/bin/racc',
                '-o', root / 'failed-calc.rb', tree / 'generator/sample/calc.y'], success=False)
            assert b'uninitialized constant Racc::Compiler::SymbolTable' in failure
    shutil.copyfile(projection / 'catalog.json', out / 'catalog.json')
    shutil.copyfile(producer / 'generated/calc.rb', out / 'generated-calc.rb')
    (out / 'upstream-README.en').write_bytes(readme)
    shutil.copyfile(input_file, out / 'inputs.json')
    shutil.copyfile(closure_file, out / 'closure-paths')
    receipt.update(complete=True, archiveVersion='1.4.4', runtimeVersion='1.4.3',
                   generatorRuby='1.8.0', consumerRuby='1.6.0', runtimeType='ruby',
                   generatorOption='--no-line-convert; diagnostic locations refer to generated file',
                   temporaryOriginalExportRootAbsent=True,
                   immutableProducerAndProjectionRetained=True,
                   generator160='FAILED original SymbolTable lookup; no workaround',
                   qualification='Local NARs physically hashed; remote artifact assertions require exact reviewed driver. No transitive or cross-day rebuild claim.')
    save()
