# SPDX-License-Identifier: MIT
# Original SDK094 owns every advertised index codec. No SDK class adapters.
require "rubygems"
raise "unsupported SDK094 index runtime" unless RUBY_VERSION == "1.8.2" && !defined?(RUBY_PATCHLEVEL) && defined?(Gem::RubyGemsVersion) && Gem::RubyGemsVersion == "0.9.4"
raise "SDK094 index cannot load Bundler" if defined?(Bundler)
require "rubygems/format"
require "rubygems/source_index"
require "fileutils"
require "yaml"
require "zlib"
require "find"
require ENV["PURIFIER_CONSUMER_PROBE"] || File.expand_path("rubygems_consumer_sdk_probe", File.dirname(__FILE__))
observation = PurifierRubyGemsConsumerProbe.observe
require ENV["PURIFIER_CONSUMER_CONTRACT"] || File.expand_path("rubygems_consumer_sdk_contract", File.dirname(__FILE__))
raise "expected SDK094 repository and attestation" unless ARGV.length == 2
attestation = PurifierRubyGemsConsumerSDKContract.read!(ARGV[1])
raise "executed SDK094 differs from attestation" unless observation == attestation.fetch("observation")
repository = File.expand_path(ARGV[0])
raise "SDK094 repository root is not canonical" unless Pathname.new(repository).realpath.to_s == repository
raise "unexpected SDK094 preexisting surface" unless (Dir.entries(repository) - [".", ".."]).sort == ["gems"] && File.directory?(File.join(repository, "gems")) && !File.symlink?(File.join(repository, "gems"))
archives = Dir.entries(File.join(repository, "gems")) - [".", ".."]
raise "unexpected SDK094 archive surface" unless archives.all? { |name| name =~ /\A[A-Za-z0-9][A-Za-z0-9_.-]*\.gem\z/ && File.file?(File.join(repository, "gems", name)) && !File.symlink?(File.join(repository, "gems", name)) }
index = Gem::SourceIndex.new({})
names = []
version = Marshal::MAJOR_VERSION.to_s + "." + Marshal::MINOR_VERSION.to_s
quick = File.join(repository, "quick")
marshal_quick = File.join(quick, "Marshal." + version)
specifications = archives.sort.map do |name|
  archive = File.join(repository, "gems", name)
  spec = Gem::Format.from_file_by_path(archive).spec
  raise "invalid SDK094 package name" unless spec.name.is_a?(String) && spec.name =~ /\A[A-Za-z0-9][A-Za-z0-9_.-]*\z/
  raise "invalid SDK094 numeric version" unless spec.version.to_s =~ /\A[0-9]+(?:\.[0-9]+)*\z/
  raise "invalid SDK094 package full name" unless spec.full_name =~ /\A[A-Za-z0-9][A-Za-z0-9_.-]*\z/
  raise "SDK094 archive filename differs from native coordinate" unless name == spec.full_name + ".gem"
  raise "duplicate SDK094 specification" if names.include?(spec.full_name)
  raise "SDK094 cannot compile source extensions" unless spec.extensions.empty?
  raise "SDK094 package requires a different Ruby" unless spec.required_ruby_version.satisfied_by?(Gem::Version.new(RUBY_VERSION))
  raise "SDK094 package platform differs" unless [Gem::Platform::RUBY, RUBY_PLATFORM].include?(spec.platform.to_s)
  names << spec.full_name
  index.add_spec(spec)
  yaml_path = File.expand_path(File.join(quick, spec.full_name + ".gemspec.rz"))
  marshal_path = File.expand_path(File.join(marshal_quick, spec.full_name + ".gemspec.rz"))
  raise "SDK094 quick path escapes repository" unless yaml_path.index(quick + "/") == 0 && marshal_path.index(marshal_quick + "/") == 0
  [[yaml_path, Zlib::Deflate.deflate(spec.to_yaml)], [marshal_path, Zlib::Deflate.deflate(Marshal.dump(spec))]]
end
bulk = [["yaml", index.to_yaml], ["Marshal." + version, Marshal.dump(index)]]
writes = specifications.inject([]) { |all, entries| all + entries }
bulk.each do |name, bytes|
  writes << [File.join(repository, name), bytes]
  writes << [File.join(repository, name + ".Z"), Zlib::Deflate.deflate(bytes)]
end
writes << [File.join(quick, "index.rz"), Zlib::Deflate.deflate(names.sort.join("\n") + "\n")]
expected = archives.map { |name| "gems/" + name } + ["yaml", "yaml.Z", "Marshal." + version, "Marshal." + version + ".Z", "quick/index.rz"]
names.each do |name|
  expected << "quick/" + name + ".gemspec.rz"
  expected << "quick/Marshal." + version + "/" + name + ".gemspec.rz"
end
raise "SDK094 endpoint manifest aliases" unless expected.uniq == expected
write_paths = writes.map { |path, bytes| path }
raise "SDK094 write manifest aliases" unless write_paths.uniq == write_paths
raise "SDK094 write path escapes repository" unless write_paths.all? { |path| File.expand_path(path) == path && path.index(repository + "/") == 0 }
expected_writes = expected.reject { |name| name.index("gems/") == 0 }.map { |name| File.join(repository, name) }
raise "SDK094 write manifest differs" unless write_paths.sort == expected_writes.sort
FileUtils.mkdir_p(marshal_quick)
writes.each do |path, bytes|
  File.open(path, "wb") { |file| file.write(bytes) }
end
actual = []
Find.find(repository) do |path|
  next if path == repository
  relative = path[(repository.length + 1)..-1]
  raise "SDK094 index contains a symlink" if File.symlink?(path)
  if File.directory?(path)
    raise "SDK094 index has an unexpected directory" unless ["gems", "quick", "quick/Marshal." + version].include?(relative)
  else
    raise "SDK094 index contains a special file" unless File.file?(path)
    actual << relative
  end
end
raise "SDK094 endpoint manifest differs" unless actual.sort == expected.sort
puts "SDK094-INDEX|" + RUBY_VERSION + "|" + Gem::RubyGemsVersion + "|" + names.length.to_s
