# SPDX-License-Identifier: MIT
"""Native codecs, duplicate bytes, reachability, provided reuse and ordinary install."""
import gzip
import hashlib
import time
import http.server
from functools import partial
import threading
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

sdk = Path(sys.argv[1])
projector = Path(sys.argv[2]).resolve()
index_sdk = Path(sys.argv[3]) if len(sys.argv) > 3 else sdk

def run(arguments, directory, environment):
    result = subprocess.run(list(map(str, arguments)), cwd=directory, env=environment,
                            text=True, capture_output=True)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout

with tempfile.TemporaryDirectory(prefix='native-codec-') as temporary:
    root = Path(temporary)
    environment = dict(os.environ, HOME=str(root), SOURCE_DATE_EPOCH="946684800")
    builder = '''require "fileutils"
require "rubygems/package"
%w[native-b native-a unused].each do |name|
  FileUtils.mkdir_p(name + "/lib")
  Dir.chdir(name) do
    body = name == "native-a" ? 'require "native_b"; NativeA=NativeB+1' : 'NativeB=41'
    path = "lib/" + name.tr("-", "_") + ".rb"
    File.open(path, "wb") { |file| file.write(body + "\\n") }
    specification = Gem::Specification.new do |spec|
      spec.name=name; spec.version="1.0.0"; spec.authors=["fixture"]
      spec.summary="Native codec proof"; spec.license="MIT"; spec.date=Time.utc(2000,1,1)
      spec.files=[path]
      spec.add_runtime_dependency("native-b", "= 1.0.0") if name == "native-a"
    end
    Gem::Package.build(specification)
  end
end
'''
    run([sdk / 'bin/ruby', '-e', builder], root, environment)
    archives = sorted(root.glob('*/*.gem'))
    duplicate = root / 'same-bytes-different-path.gem'
    shutil.copyfile(next(p for p in archives if p.name.startswith('native-a-')), duplicate)
    archives.append(duplicate)
    request = dict(identity='first', projectorIdentity='native-codec-v1', archives=list(map(str, archives)),
                   archiveIdentities={str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in archives},
                   roots=['native-a'])

    def project(name, value):
        path = root / (name + '.json')
        path.write_text(json.dumps(value))
        repository, catalog = root / name, root / (name + '-catalog.json')
        native = dict(environment, PURIFIER_RUBYGEMS_SEPARATE_INDEX="1")
        run([sdk / 'bin/ruby', projector, path, repository, catalog], root, native)
        run([index_sdk / 'bin/ruby', projector.with_name('rubygems_index.rb'), repository, catalog], root, environment)
        content = json.loads(catalog.read_text())
        return repository, catalog, content

    repository, catalog, content = project('first', request)
    time.sleep(2)
    repeat, _, repeated = project('repeat', dict(request, identity='independent'))
    assert content == repeated, json.dumps([content, repeated], indent=2)
    assert catalog.read_bytes() == (root / 'repeat-catalog.json').read_bytes()
    for path in repository.rglob('*'):
        if path.is_file():
            other = repeat / path.relative_to(repository)
            assert path.read_bytes() == other.read_bytes(), (str(path), path.read_bytes()[:24].hex(), other.read_bytes()[:24].hex(), gzip.decompress(path.read_bytes()) == gzip.decompress(other.read_bytes()) if path.suffix == '.gz' else None)
    packages = {entry['name']: entry for entry in content['packages']}
    assert set(packages) == {'native-a', 'native-b'}
    for entry in packages.values():
        assert (repository / entry['archive']).read_bytes() == (repeat / entry['archive']).read_bytes()
    a = repository / packages['native-a']['archive']
    requirement = run([sdk / 'bin/ruby', '-e',
        'require "rubygems/package"; print Gem::Package.new(ARGV[0]).spec.runtime_dependencies.first.requirement', a], root, environment)
    assert requirement == '= ' + packages['native-b']['version'], requirement
    reuse, _, reused = project('reuse', dict(identity='consumer', archives=[], roots=['native-a'],
                                             dependencies=[dict(repository=str(repository), catalog=str(catalog))]))
    assert reused == content
    home = root / 'ordinary'
    ordinary = dict(environment, GEM_HOME=str(home), GEM_PATH=os.pathsep.join([str(home), str(sdk / 'lib/ruby/gems')]))
    for name in ('native-b', 'native-a'):
        entry = packages[name]
        assert (reuse / entry['archive']).read_bytes() == (repository / entry['archive']).read_bytes()
        run([sdk / 'bin/gem', 'install', '--local', '--no-document', reuse / entry['archive']], root, ordinary)
    assert run([sdk / 'bin/ruby', '-e', 'require "rubygems"; require "native_a"; print NativeA'], root, ordinary) == '42'
    if os.environ.get('CODEC_NATIVE_HTTP') == '1':
        class Handler(http.server.SimpleHTTPRequestHandler):
            def log_message(self, *_):
                pass
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(repository)))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            remote_home = root / 'ordinary-http'
            remote = dict(environment, GEM_HOME=str(remote_home), GEM_PATH=str(remote_home))
            run([sdk / 'bin/gem', 'install', '--no-document', '--clear-sources', '--prerelease',
                 '--source', 'http://127.0.0.1:' + str(server.server_port),
                 'native-a', '--version', packages['native-a']['version']], root, remote)
            assert run([sdk / 'bin/ruby', '-e', 'require "rubygems"; require "native_a"; print NativeA'], root, remote) == '42'
            print('PASS ordinary native registry-index resolution, download, install and execution')
        finally:
            server.shutdown()
            server.server_close()
    version = run([sdk / 'bin/ruby', '-e', 'print RUBY_VERSION'], root, environment)
    print('PASS Ruby ' + version + ': native codec, duplicate-byte deduplication, reachable graph, exact pins, repeatable archives, provided reuse, ordinary execution')
