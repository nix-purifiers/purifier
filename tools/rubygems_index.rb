# SPDX-License-Identifier: MIT
# This helper reads native archives; it never loads project code or changes payloads.
require "rubygems/package"
require "json"
require "fileutils"
require "zlib"

repository, catalog = ARGV
entries = JSON.parse(File.read(catalog)).fetch("packages")
FileUtils.mkdir_p(File.join(repository, "quick", "Marshal.4.8"))
entries.each do |entry|
  specification = Gem::Package.new(File.join(repository, entry.fetch("archive"))).spec
  quick = File.join(repository, "quick", "Marshal.4.8", "#{specification.original_name}.gemspec.rz")
  File.open(quick, "wb") { |file| file.write(Zlib::Deflate.deflate(Marshal.dump(specification))) }
end
specs = entries.map { |entry| [entry.fetch("name"), Gem::Version.new(entry.fetch("version")), entry.fetch("platform")] }.sort
{
  "specs" => specs.reject { |_, version, _| version.prerelease? },
  "latest_specs" => specs.reject { |_, version, _| version.prerelease? }.group_by { |name, _, platform| [name, platform] }.values.map { |values| values.max_by { |_, version, _| version } }.sort,
  "prerelease_specs" => specs.select { |_, version, _| version.prerelease? },
}.each do |kind, values|
  Zlib::GzipWriter.open(File.join(repository, "#{kind}.4.8.gz")) do |writer|
    writer.mtime = 0
    writer.write(Marshal.dump(values))
  end
end
