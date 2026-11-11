# SPDX-License-Identifier: MIT
"""Modern projection bytes must pin dependencies for native older consumers."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("producer", type=Path)
parser.add_argument("projector", type=Path)
parser.add_argument("consumers", nargs="*", type=Path)
parser.add_argument("--output", type=Path)
args = parser.parse_args()


def run(argv, cwd, env):
    result = subprocess.run(list(map(str, argv)), cwd=cwd, env=env,
                            capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


builder = r'''
require "rubygems/package"
require "fileutils"
[["wire-leaf", "1.0.0", "WireLeaf=42"],
 ["wire-leaf", "9.0.0", "WireLeaf=-1"],
 ["wire-unbound", "2.0.0", ""],
 ["wire-root", "1.0.0", "require 'wire_leaf'; WireRoot=WireLeaf"]].each do |name, version, body|
  Dir.mkdir(name+version)
  Dir.chdir(name+version) do
    Dir.mkdir("lib")
    File.write("lib/"+name.tr("-", "_")+".rb", body+"\n")
    spec = Gem::Specification.new do |s|
      s.name=name; s.version=version; s.summary="native dependency wire regression"
      s.authors=["fixture"]; s.files=Dir["lib/*.rb"]
      if name == "wire-root"
        s.add_runtime_dependency("wire-leaf", ">= 1")
        s.dependencies.last.prerelease = true
        s.add_runtime_dependency("wire-unbound", ">= 2")
        s.add_development_dependency("wire-leaf", "< 3")
      end
    end
    FileUtils.cp(Gem::Package.build(spec), "../"+name+"-"+version+".gem")
  end
end
'''

consumer = r'''
require "rubygems"
require "zlib"
if Gem::VERSION.split(".").first.to_i < 2
  require "rubygems/format"
  archive_spec = Gem::Format.from_file_by_path(ARGV[0]).spec
else
  require "rubygems/package"
  archive_spec = Gem::Package.new(ARGV[0]).spec
end
index_spec = Marshal.load(Zlib::Inflate.inflate(File.read(ARGV[1])))
expected = ARGV[2]
[archive_spec, index_spec].each do |spec|
  runtime = spec.dependencies.select { |d| d.type == :runtime }
  pinned = runtime.find { |d| d.name == "wire-leaf" }
  requirement = pinned.respond_to?(:requirement) ? pinned.requirement : pinned.version_requirements
  abort "stale serialized requirement: #{requirement}" unless requirement.to_s == "= "+expected
  abort "native matching rejected pin" unless pinned =~ Gem::Specification.new { |s| s.name="wire-leaf"; s.version=expected }
  abort "native matching accepted competitor" if pinned =~ Gem::Specification.new { |s| s.name="wire-leaf"; s.version="9.0.0" }
  if pinned.respond_to?(:prerelease?)
    abort "prerelease option lost" unless pinned.prerelease?
  end
  unbound = runtime.find { |d| d.name == "wire-unbound" }
  req = unbound.respond_to?(:requirement) ? unbound.requirement : unbound.version_requirements
  abort "unbound runtime changed" unless req.to_s == ">= 2"
  development = spec.dependencies.find { |d| d.type == :development }
  req = development.respond_to?(:requirement) ? development.requirement : development.version_requirements
  abort "development dependency changed" unless development.name == "wire-leaf" && req.to_s == "< 3"
end
puts "WIRE|#{RUBY_VERSION}|#{Gem::VERSION}|#{expected}"
'''

installer = r'''
require "rubygems"
require "rubygems/installer"
ARGV.each do |archive|
  options = {:install_dir=>ENV.fetch("GEM_HOME"), :ignore_dependencies=>true, :wrappers=>false}
  if Gem::Installer.respond_to?(:at)
    Gem::Installer.at(archive, options).install
  else
    Gem::Installer.new(archive, options).install
  end
end
'''

results = []
with tempfile.TemporaryDirectory(prefix="rubygems-wire-") as tmp:
    root = Path(tmp)
    env = {k: v for k, v in os.environ.items() if not k.startswith(("RUBY", "GEM_", "BUNDLE_"))}
    env.update(HOME=str(root), SOURCE_DATE_EPOCH="1")
    ruby = args.producer / "bin/ruby"
    run([ruby, "-e", builder], root, env)
    request = root / "request.json"
    request.write_text(json.dumps({"identity": "wire-regression", "archives": [
        str(root / "wire-root-1.0.0.gem"), str(root / "wire-leaf-1.0.0.gem")]}))
    repository, catalog = root / "repository", root / "catalog.json"
    run([ruby, args.projector.resolve(), request, repository, catalog], root, env)
    entries = {e["name"]: e for e in json.loads(catalog.read_text())["packages"]}
    parent, leaf = entries["wire-root"], entries["wire-leaf"]
    archive = repository / parent["archive"]
    quick = repository / "quick/Marshal.4.8" / (parent["name"]+"-"+parent["version"]+".gemspec.rz")
    for index, sdk in enumerate(args.consumers or [args.producer]):
        native = sdk / "bin/ruby"
        wire = run([native, "-e", consumer, archive, quick, leaf["version"]], root, env)
        home = root / ("installed-"+str(index))
        ordinary = dict(env, GEM_HOME=str(home), GEM_PATH=str(home))
        run([native, "-e", installer, root / "wire-leaf-9.0.0.gem", root / "wire-unbound-2.0.0.gem",
             repository / leaf["archive"], archive], root, ordinary)
        runtime = run([native, "-e", 'require "rubygems"; require "wire_root"; puts WireRoot; '
                       'puts Gem.loaded_specs["wire-leaf"].version; '
                       'abort "leaf not loaded" unless $LOADED_FEATURES.any? { |f| f =~ /wire_leaf.rb$/ }; '
                       'puts $LOAD_PATH.map { |p| File.expand_path(File.join(p,"wire_leaf.rb")) }.find { |p| File.file?(p) }'], root, ordinary).splitlines()
        assert runtime[0:2] == ["42", leaf["version"]], runtime
        loaded = Path(runtime[2])
        assert home in loaded.parents and leaf["version"] in str(loaded), runtime
        assert loaded.read_bytes() == b"WireLeaf=42\n"
        results.append({"consumer": str(sdk), "wire": wire.strip(), "value": 42,
                        "loadedVersion": leaf["version"], "loadedBytesSha256": hashlib.sha256(loaded.read_bytes()).hexdigest(),
                        "competitorRejected": "9.0.0", "archiveSha256": hashlib.sha256(archive.read_bytes()).hexdigest()})
        print("PASS "+wire.strip()+": archive/Marshal requirements, native activation and exact loaded bytes")
if args.output:
    args.output.write_text(json.dumps({"producer": str(args.producer), "projector": str(args.projector),
                                      "projectorSha256": hashlib.sha256(args.projector.read_bytes()).hexdigest(),
                                      "results": results}, indent=2)+"\n")
