# SPDX-License-Identifier: MIT
# The selected legacy SDK owns SourceIndex and specification serialization.
require "rubygems"
raise "unsupported native legacy index SDK" unless RUBY_VERSION == "1.8.3" && defined?(Gem::RubyGemsVersion) && Gem::RubyGemsVersion == "1.0.1"
require "rubygems/exceptions"
require "rubygems/format"
require "rubygems/source_index"
require "fileutils"
require "zlib"
raise "expected one native repository" unless ARGV.length == 1
repository = File.expand_path(ARGV[0])
index = Gem::SourceIndex.new({})
names = []
Dir[File.join(repository, "gems", "*.gem")].sort.each do |archive|
  spec = Gem::Format.from_file_by_path(archive).spec
  raise "duplicate native specification" if names.include?(spec.original_name)
  names << spec.original_name
  index.add_spec(spec)
  quick = File.join(repository, "quick", "Marshal." + Gem.marshal_version)
  FileUtils.mkdir_p(quick)
  File.open(File.join(quick, spec.original_name + ".gemspec.rz"), "wb") do |file|
    file.write(Zlib::Deflate.deflate(Marshal.dump(spec)))
  end
end
bytes = Marshal.dump(index)
File.open(File.join(repository, "Marshal." + Gem.marshal_version), "wb") { |file| file.write(bytes) }
File.open(File.join(repository, "Marshal." + Gem.marshal_version + ".Z"), "wb") { |file| file.write(Zlib::Deflate.deflate(bytes)) }
FileUtils.mkdir_p(File.join(repository, "quick"))
File.open(File.join(repository, "quick", "index.rz"), "wb") { |file| file.write(Zlib::Deflate.deflate(names.sort.join("\n") + "\n")) }
puts "LEGACY-INDEX|" + RUBY_VERSION + "|" + Gem::RubyGemsVersion + "|" + names.length.to_s
