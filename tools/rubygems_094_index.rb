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
raise "unexpected SDK094 preexisting surface" unless (Dir.entries(repository) - [".", ".."]).sort == ["gems"] && File.directory?(File.join(repository, "gems")) && !File.symlink?(File.join(repository, "gems"))
archives = Dir.entries(File.join(repository, "gems")) - [".", ".."]
raise "unexpected SDK094 archive surface" unless archives.all? { |name| name =~ /\A[^\/]+\.gem\z/ && File.file?(File.join(repository, "gems", name)) && !File.symlink?(File.join(repository, "gems", name)) }
index = Gem::SourceIndex.new({})
names = []
version = Marshal::MAJOR_VERSION.to_s + "." + Marshal::MINOR_VERSION.to_s
quick = File.join(repository, "quick")
marshal_quick = File.join(quick, "Marshal." + version)
specifications = Dir[File.join(repository, "gems", "*.gem")].sort.map do |archive|
  spec = Gem::Format.from_file_by_path(archive).spec
  raise "duplicate SDK094 specification" if names.include?(spec.full_name)
  raise "SDK094 cannot compile source extensions" unless spec.extensions.empty?
  raise "SDK094 package requires a different Ruby" unless spec.required_ruby_version.satisfied_by?(Gem::Version.new(RUBY_VERSION))
  raise "SDK094 package platform differs" unless [Gem::Platform::RUBY, RUBY_PLATFORM].include?(spec.platform.to_s)
  names << spec.full_name
  index.add_spec(spec)
  spec
end
FileUtils.mkdir_p(marshal_quick)
specifications.each do |spec|
  [[File.join(quick, spec.full_name + ".gemspec.rz"), spec.to_yaml],
   [File.join(marshal_quick, spec.full_name + ".gemspec.rz"), Marshal.dump(spec)]].each do |path, bytes|
    File.open(path, "wb") { |file| file.write(Zlib::Deflate.deflate(bytes)) }
  end
end
[["yaml", index.to_yaml], ["Marshal." + version, Marshal.dump(index)]].each do |name, bytes|
  File.open(File.join(repository, name), "wb") { |file| file.write(bytes) }
  File.open(File.join(repository, name + ".Z"), "wb") { |file| file.write(Zlib::Deflate.deflate(bytes)) }
end
File.open(File.join(quick, "index.rz"), "wb") { |file| file.write(Zlib::Deflate.deflate(names.sort.join("\n") + "\n")) }
expected = archives.map { |name| "gems/" + name } + ["yaml", "yaml.Z", "Marshal." + version, "Marshal." + version + ".Z", "quick/index.rz"]
names.each do |name|
  expected << "quick/" + name + ".gemspec.rz"
  expected << "quick/Marshal." + version + "/" + name + ".gemspec.rz"
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
