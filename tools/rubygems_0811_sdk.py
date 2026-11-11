# SPDX-License-Identifier: MIT
"""Measure an independent ordinary RubyGems SDK. No Bundler schema reuse."""

import ast
import base64
import hashlib
import json
import os
import selectors
import signal
import subprocess
import sys
import tempfile
import time
import re
import gzip
import io
import tarfile
from pathlib import Path


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate SDK field")
        result[key] = value
    return result


def read(path):
    with Path(path).open("rb") as source:
        raw = source.read(1048577)
    if len(raw) > 1048576:
        raise ValueError("SDK descriptor exceeds bound")
    return json.loads(raw, object_pairs_hook=unique)


def run(args, env=None, deadline_seconds=90, output_limit=8388608):
    child = subprocess.Popen(
        args,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    selector = selectors.DefaultSelector()
    output = [bytearray(), bytearray()]
    try:
        for index, stream in enumerate((child.stdout, child.stderr)):
            os.set_blocking(stream.fileno(), False)
            selector.register(stream, selectors.EVENT_READ, index)
        deadline = time.monotonic() + deadline_seconds
        while selector.get_map() or child.poll() is None:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError("SDK command deadline exceeded")
            for key, _ in selector.select(min(remaining, 0.05)):
                data = os.read(key.fileobj.fileno(), 65536)
                if not data:
                    selector.unregister(key.fileobj)
                    continue
                output[key.data].extend(data)
                if sum(map(len, output)) > output_limit:
                    raise ValueError("SDK output exceeds bound")
        if child.returncode:
            raise ValueError(
                "SDK command failed: " + output[1].decode(errors="replace")
            )
        return output[0].decode()
    finally:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait(timeout=5)
        selector.close()
        child.stdout.close()
        child.stderr.close()


PROFILE = 'ruby180-rubygems0811-i686-v1'
ARCHIVES = {'ruby': 'sha256-EVxf4KFXCavRtkNRqhvtnAMNHz13ytPy8rULNwTCAfE=',
            'rubygems': 'sha256-x+2bn1DqzpXa7EkXRM0yLnTAZg3QAZ85n1TIW7cCtf8='}

def exact(value, fields):
    if type(value) is not dict or set(value) != set(fields.split()):
        raise ValueError('invalid0811 fields')


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sri(path):
    return 'sha256-' + base64.b64encode(bytes.fromhex(sha(path))).decode()


BOOTSTRAP_POLICY = dict(format='original0811-sources-bootstrap', schemaVersion=1,
                        date='1970-01-01', timezone='UTC', generatedCache='absent')
SOURCE_MEMBERS = {'sources.gemspec':'pkgs/sources/sources.gemspec',
                  'lib/sources.rb':'pkgs/sources/lib/sources.rb'}

def original_sources(archive):
    if sri(archive) != ARCHIVES['rubygems']:
        raise ValueError('not the original0811 source archive')
    with tarfile.open(archive) as outer:
        data = [m for m in outer if m.name == 'data.tar.gz' and m.isfile()]
        if len(data) != 1 or data[0].size > 8388608:
            raise ValueError('invalid original0811 payload surface')
        compressed = outer.extractfile(data[0]).read()
    uncompressed = gzip.decompress(compressed)
    if len(uncompressed) > 16777216:
        raise ValueError('oversized original0811 payload')
    with tarfile.open(fileobj=io.BytesIO(uncompressed)) as inner:
        result = {}
        for name, member in SOURCE_MEMBERS.items():
            matches = [m for m in inner.getmembers() if m.name == member and m.isfile()]
            if len(matches) != 1 or matches[0].size > 65536:
                raise ValueError('invalid original0811 embedded sources')
            result[name] = inner.extractfile(matches[0]).read()
    return result


def attest(descriptor, closure_file, nix, runtime_ruby, probe, sources_helper):
    exact(descriptor, 'schemaVersion profile sdk compiler buildEnvironment originalSources bootstrapPolicy runtimeBuild stdenvBuild compilerBuild sdkBuild components')
    if type(descriptor['schemaVersion']) is not int or descriptor['schemaVersion'] != 1 or descriptor['profile'] != PROFILE:
        raise ValueError('unsupported0811 descriptor')
    paths = Path(closure_file).read_text().splitlines()
    if not 1 <= len(paths) <= 4096 or paths != sorted(set(paths)):
        raise ValueError('invalid0811 closure')
    for path in paths:
        if not re.fullmatch(r'/nix/store/[a-z0-9]{32}-[A-Za-z0-9+._?=-]+', path) or str(Path(path).resolve(strict=True)) != path:
            raise ValueError('invalid0811 immutable closure root')
    def inside(path):
        return any(path == root or path.startswith(root + '/') for root in paths)
    def physical(path):
        if not isinstance(path, str) or not inside(path) or str(Path(path).resolve(strict=True)) != path:
            raise ValueError('0811 provenance escapes actual closure')
        return path
    underlying = physical(descriptor['sdk'])
    wrapper = physical(str(Path(runtime_ruby).parent.parent))
    compiler = physical(descriptor['compiler'])
    source_tree = physical(descriptor['originalSources'])
    if descriptor['bootstrapPolicy'] != BOOTSTRAP_POLICY or type(descriptor['bootstrapPolicy'].get('schemaVersion')) is not int:
        raise ValueError('unsupported0811 bootstrap policy')
    build_environment = physical(descriptor['buildEnvironment'])
    env = {k:v for k,v in os.environ.items() if not k.startswith(('RUBY','GEM_','BUNDLE_','BUNDLER_')) and k.lower() not in ('http_proxy','https_proxy','all_proxy')}
    with tempfile.TemporaryDirectory(prefix='sdk0811-') as temp:
        env.update(HOME=temp,GEM_HOME=temp+'/gems',GEM_PATH=temp+'/gems',TZ='UTC')
        raw = run([runtime_ruby, probe], env)
        observation = json.loads(raw,object_pairs_hook=unique)
        if raw != canonical(observation)+'\n':
            raise ValueError('noncanonical0811 native observation')
        compiler_version = run([compiler+'/bin/gcc','--version'], env)
        compiler_target = run([compiler+'/bin/gcc','-dumpmachine'], env).strip()
    exact(observation,'ruby patchlevel abi platform nixSystem pointerBytes elfClass elfMachine executable interpreterSha256 rubygemsReport rubyLibrary rubygemsLibrary installed specificationFiles bundlerLoaded')
    required = dict(ruby='1.8.0',patchlevel=None,abi='1.8',platform='i686-linux-gnu',nixSystem='i686-linux',pointerBytes=4,elfClass=32,elfMachine=3,bundlerLoaded=False,rubygemsReport={'name':'Gem::RubyGemsVersion','value':'0.8.11'})
    if any(type(observation[k]) is not type(v) or observation[k] != v for k,v in required.items()):
        raise ValueError('0811 native runtime differs')
    executable = physical(observation['executable'])
    elf = Path(executable).read_bytes()[:20]
    if sha(executable) != observation['interpreterSha256'] or elf[:6] != b'\x7fELF\x01\x01' or int.from_bytes(elf[18:20],'little') != 3:
        raise ValueError('0811 actual executable ABI differs')
    version_match = re.fullmatch(r'gcc \(GCC\) ([0-9]+(?:\.[0-9]+)+)', compiler_version.splitlines()[0])
    if compiler_target != 'i686-pc-linux-gnu' or not version_match or version_match.group(1) != '4.8.3':
        raise ValueError('0811 native compiler differs')
    installed = observation['installed']; specifications = observation['specificationFiles']
    if type(installed) is not list or len(installed) != 1 or type(specifications) is not list or len(specifications) != 1:
        raise ValueError('0811 installed set differs')
    exact(installed[0],'name version library'); exact(specifications[0],'path sha256')
    if installed[0]['name'] != 'sources' or installed[0]['version'] != '0.0.1':
        raise ValueError('0811 bundled sources differ')
    physical(installed[0]['library']); spec = physical(specifications[0]['path'])
    if not spec.endswith('/specifications/sources-0.0.1.gemspec') or sha(spec) != specifications[0]['sha256']:
        raise ValueError('0811 installed specification changed')
    if spec != str(Path(installed[0]['library']).parent.parent/'specifications/sources-0.0.1.gemspec'):
        raise ValueError('0811 source coordinate differs')
    components = descriptor['components']
    if type(components) is not list or len(components) != 2 or {c['name']:c['version'] for c in components} != {'ruby':'1.8.0','rubygems':'0.8.11'}:
        raise ValueError('0811 original components differ')
    measured=[]
    def nar(path):
        return run([nix,'--extra-experimental-features','nix-command','hash','path',path]).strip()
    for item in components:
        exact(item,'name version archive library'); name=item['name']; archive=physical(item['archive']); library=physical(item['library'])
        if sri(archive) != ARCHIVES[name] or library != observation[name+'Library']:
            raise ValueError('0811 original archive/library join differs')
        measured.append(dict(item,archiveHash=sri(archive),libraryHash=nar(library)))
    provenance={}; builds={}
    for key in ['runtimeBuild','stdenvBuild','compilerBuild','sdkBuild']:
        source=descriptor[key];exact(source,'captured original'); captured=physical(source['captured'])
        if not re.fullmatch(r'/nix/store/[a-z0-9]{32}-[A-Za-z0-9+._?=-]+\.drv',source['original']):
            raise ValueError('invalid0811 original derivation coordinate')
        raw=Path(captured).open().read(8388609)
        if len(raw)>8388608 or not raw.startswith('Derive('):
            raise ValueError('invalid0811 derivation bytes')
        build=ast.literal_eval(raw[len('Derive'):]); builds[key]=build
        provenance[key]=dict(source,sha256=sha(captured))
    runtime,stdenv,compiler_drv,sdk_build=[builds[k] for k in ['runtimeBuild','stdenvBuild','compilerBuild','sdkBuild']]
    runtime_env=dict(runtime[6]); sdk_env=dict(sdk_build[6]); stdenv_outputs=[r[1] for r in stdenv[0]]
    if runtime[3] != 'i686-linux' or runtime_env.get('system') != 'i686-linux' or runtime_env.get('CC') != 'gcc' or runtime_env.get('stdenv') != build_environment or build_environment not in stdenv_outputs or descriptor['stdenvBuild']['original'] not in dict(runtime[1]):
        raise ValueError('0811 actual runtime/stdenv system join differs')
    ruby_component=next(c for c in measured if c['name']=='ruby'); gem_component=next(c for c in measured if c['name']=='rubygems')
    if ruby_component['library'] not in [r[1] for r in runtime[0]] or runtime_env.get('src') != ruby_component['archive']:
        raise ValueError('0811 original Ruby archive/output differs')
    setup=Path(physical(runtime_env['stdenv']+'/setup'));setup_text=setup.read_text()
    defaults=re.search(r'^defaultNativeBuildInputs="([^"\n]*)"$',setup_text,re.M)
    if not defaults or compiler not in defaults.group(1).split() or compiler not in [r[1] for r in compiler_drv[0]] or descriptor['compilerBuild']['original'] not in dict(stdenv[1]):
        raise ValueError('0811 actual implicit compiler/stdenv join differs')
    if gem_component['library'] not in [r[1] for r in sdk_build[0]] or gem_component['archive'] not in sdk_env.get('buildCommand','') or ruby_component['library'] not in sdk_env.get('buildCommand',''):
        raise ValueError('0811 original bootstrap archive/runtime/output differs')
    if sdk_env.get('bootstrapPolicyVersion') != '1' or sdk_env.get('bootstrapDate') != '1970-01-01' or sdk_env.get('TZ') != 'UTC':
        raise ValueError('0811 actual bootstrap build policy differs')
    cache = gem_component['library']+'/gems/cache/sources-0.0.1.gem'
    if Path(cache).exists() or Path(cache).is_symlink():
        raise ValueError('0811 transient generated cache was not removed')
    embedded = original_sources(gem_component['archive'])
    entries=list(Path(source_tree).rglob('*'))
    if any(p.is_symlink() or not (p.is_dir() or p.is_file()) for p in entries) or sorted(str(p.relative_to(source_tree)) for p in entries) != ['lib','lib/sources.rb','sources.gemspec']:
        raise ValueError('0811 original embedded source tree differs')
    for name, data in embedded.items():
        if Path(physical(source_tree+'/'+name)).read_bytes() != data:
            raise ValueError('0811 embedded source bytes changed')
    # Only the byte-verified original factory may be executed. The source tree
    # lives in immutable Nix store paths, so this check cannot race a mutable input.
    with tempfile.TemporaryDirectory(prefix='sources0811-') as temp:
        env.update(HOME=temp,GEM_HOME=temp+'/gems',GEM_PATH=temp+'/gems',TZ='UTC')
        expected_specification = run([runtime_ruby,sources_helper,source_tree],env).encode('ascii')
    if Path(spec).read_bytes() != expected_specification:
        raise ValueError('0811 installed spec differs from original native source factory')
    source_library = installed[0]['library']
    installed_files = list(Path(source_library).rglob('*'))
    if any(p.is_symlink() or not (p.is_dir() or p.is_file()) for p in installed_files) or sorted(str(p.relative_to(source_library)) for p in installed_files) != ['lib','lib/sources.rb']:
        raise ValueError('0811 installed bundled source payload surface differs')
    payload = physical(source_library+'/lib/sources.rb')
    if Path(payload).read_bytes() != embedded['lib/sources.rb']:
        raise ValueError('0811 installed sources differ from original embedded payload')
    bundled = dict(library=source_library,libraryHash=nar(source_library),originalSources=source_tree,
                   definitionSha256=hashlib.sha256(embedded['sources.gemspec']).hexdigest(),
                   payload=payload,payloadSha256=sha(payload),specification=spec,
                   specificationSha256=sha(spec),cachePath=cache,cacheAbsent=True)

    return dict(format='rubygems-native-consumer-sdk-0811-i686',schemaVersion=1,profile=PROFILE,serializerVersion='ascii-primitives-v1',sdk=wrapper,underlyingSdk=underlying,observation=observation,components=sorted(measured,key=lambda c:c['name']),bootstrapPolicy=BOOTSTRAP_POLICY,bundledSources=bundled,compiler=dict(path=compiler,narHash=nar(compiler),versionOutput=compiler_version,target=compiler_target),provenance=provenance,stdenvSetup=dict(path=str(setup),sha256=sha(setup)),closure=[dict(path=p,narHash=nar(p)) for p in paths])

if __name__ == '__main__':
    # Descriptor is a measured constructor input. Verification remeasures the
    # actual native executable and independent Nix-exported closure each time.
    if len(sys.argv) == 4 and sys.argv[1] == 'extract-original':
        archive, output = sys.argv[2:]
        embedded = original_sources(archive)
        for name, data in embedded.items():
            target = Path(output)/name
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_bytes(data)
        raise SystemExit(0)
    mode, descriptor, closure, nix, document, ruby, probe, sources_helper = sys.argv[1:]
    if mode not in ('create','verify'):
        raise ValueError('unsupported0811 mode')
    measured=attest(read(descriptor),closure,nix,ruby,probe,sources_helper)
    encoded=canonical(measured)+'\n'
    if mode=='create':
        Path(document).write_text(encoded)
    elif read(document)!=measured or Path(document).read_text()!=encoded:
        raise ValueError('0811 executed SDK/physical provenance differs from attestation')
    else:
        print('ORDINARY-SDK-VERIFIED|'+PROFILE)
