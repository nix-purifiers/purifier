# SPDX-License-Identifier: MIT
# Original SDK0811 owns every advertised index codec. No SDK class adapters. Only the original remote YAML protocol is advertised.
require "rubygems"
Gem.manage_gems
raise "unsupported SDK0811 index runtime" unless RUBY_VERSION == "1.8.0" && !defined?(RUBY_PATCHLEVEL) && RUBY_PLATFORM == "i686-linux-gnu" && Gem::RubyGemsVersion == "0.8.11"
raise "SDK0811 index cannot load Bundler" if defined?(Bundler)
require "fileutils"
require "yaml"
require "zlib"
require "find"
require ENV["PURIFIER_CONSUMER_PROBE"] || File.expand_path("rubygems_0811_probe", File.dirname(__FILE__))
raise "expected SDK0811 repository and verified observation" unless ARGV.length == 2
# Host contract validates the complete attestation/identity/closure before this
# original-native encoder. Never parse caller JSON with eval or native YAML.
observation = PurifierRubyGems0811Probe.canonical(PurifierRubyGems0811Probe.observe) + "\n"
expected = File.open(ARGV[1], "rb") { |file| file.read(1048577) }
raise "executed SDK0811 differs from verified observation" unless expected.length <= 1048576 && observation == expected
repository = File.expand_path(ARGV[0])
raise "SDK0811 repository root is not canonical" unless Pathname.new(repository).realpath.to_s == repository
raise "unexpected SDK0811 preexisting surface" unless (Dir.entries(repository) - [".", ".."]).sort == ["gems"] && File.directory?(File.join(repository, "gems")) && !File.symlink?(File.join(repository, "gems"))
archives = Dir.entries(File.join(repository, "gems")) - [".", ".."]
raise "unexpected SDK0811 archive surface" unless archives.all? { |name| name =~ /\A[A-Za-z0-9][A-Za-z0-9_.-]*\.gem\z/ && File.file?(File.join(repository, "gems", name)) && !File.symlink?(File.join(repository, "gems", name)) }
specification_hash = {}
names = []
archives.sort.each do |name|
  archive = File.join(repository, "gems", name)
  spec = Gem::Format.from_file_by_path(archive).spec
  raise "invalid SDK0811 package name" unless spec.name.is_a?(String) && spec.name =~ /\A[A-Za-z0-9][A-Za-z0-9_.-]*\z/
  raise "invalid SDK0811 numeric version" unless spec.version.to_s =~ /\A[0-9]+(?:\.[0-9]+)*\z/
  raise "invalid SDK0811 package full name" unless spec.full_name =~ /\A[A-Za-z0-9][A-Za-z0-9_.-]*\z/
  raise "SDK0811 archive filename differs from native coordinate" unless name == spec.full_name + ".gem"
  raise "duplicate SDK0811 specification" if names.include?(spec.full_name)
  raise "SDK0811 cannot compile source extensions" unless spec.extensions.empty?
  raise "SDK0811 package requires a different Ruby" unless spec.required_ruby_version.satisfied_by?(Gem::Version.new(RUBY_VERSION))
  raise "SDK0811 package platform differs" unless spec.platform.to_s == "ruby"
  names << spec.full_name
  specification_hash[spec.full_name] = spec
end
index = Gem::SourceIndex.new(specification_hash)
yaml = index.to_yaml
writes = [[File.join(repository, "yaml"), yaml], [File.join(repository, "yaml.Z"), Zlib::Deflate.deflate(yaml)]]
expected = archives.map { |name| "gems/" + name } + ["yaml", "yaml.Z"]
raise "SDK0811 endpoint manifest aliases" unless expected.uniq == expected
write_paths = writes.map { |path, bytes| path }
raise "SDK0811 write manifest aliases" unless write_paths.uniq == write_paths
raise "SDK0811 write path escapes repository" unless write_paths.all? { |path| File.expand_path(path) == path && path.index(repository + "/") == 0 }
expected_writes = expected.reject { |name| name.index("gems/") == 0 }.map { |name| File.join(repository, name) }
raise "SDK0811 write manifest differs" unless write_paths.sort == expected_writes.sort
writes.each do |path, bytes|
  File.open(path, "wb") { |file| file.write(bytes) }
end
actual = []
Find.find(repository) do |path|
  next if path == repository
  relative = path[(repository.length + 1)..-1]
  raise "SDK0811 index contains a symlink" if File.symlink?(path)
  if File.directory?(path)
    raise "SDK0811 index has an unexpected directory" unless relative == "gems"
  else
    raise "SDK0811 index contains a special file" unless File.file?(path)
    actual << relative
  end
end
raise "SDK0811 endpoint manifest differs" unless actual.sort == expected.sort
puts "SDK0811-INDEX|" + RUBY_VERSION + "|" + Gem::RubyGemsVersion + "|" + names.length.to_s
