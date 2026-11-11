# SPDX-License-Identifier: MIT
# Build a native RubyGems repository using the target SDK's own package codecs.
require "rubygems/package"
require File.expand_path("rubygems_codec.rb", File.dirname(__FILE__)) unless ENV["PURIFIER_RUBYGEMS_CODEC_PRELOADED"] == "1"
require "json"
require "fileutils"
require "tmpdir"
require "zlib"
require "digest"
require "base64"
require File.expand_path("rubygems_version_scheme.rb", File.dirname(__FILE__))

specification = JSON.parse(File.read(ARGV.fetch(0)))
version_scheme, native_sdk_identity = PurifierRubyGemsVersionScheme.configuration(specification)
destination = ARGV.fetch(1)
catalog_path = ARGV.fetch(2)
intrinsics = {}

def add_intrinsic(intrinsics, entry)
  name = entry.fetch("name")
  raise "conflicting Ruby SDK inputs for #{name}" if intrinsics.key?(name) && intrinsics[name] != entry
  intrinsics[name] = entry
end
specification.fetch("intrinsics", []).each { |entry| add_intrinsic(intrinsics, entry) }
packages = specification.fetch("archives").map do |archive|
  [archive, Gem::Package.new(archive).spec, nil]
end
specification.fetch("dependencies", []).each do |input|
  catalog = JSON.parse(File.read(input.fetch("catalog")))
  catalog.fetch("intrinsics", []).each { |entry| add_intrinsic(intrinsics, entry) }
  catalog.fetch("packages").each do |entry|
    PurifierRubyGemsVersionScheme.validate_provided!(entry, version_scheme, native_sdk_identity)
    archive = File.join(input.fetch("repository"), entry.fetch("archive"))
    actual = "sha512-#{Base64.encode64(Digest::SHA512.file(archive).digest).delete("\n")}"
    raise "RubyGems input archive integrity mismatch: #{archive}" unless actual == entry.fetch("integrity")
    gem_spec = Gem::Package.new(archive).spec
    unless [gem_spec.name, gem_spec.version.to_s, gem_spec.platform.to_s] == entry.values_at("name", "version", "platform")
      raise "RubyGems input catalog coordinates do not match #{archive}"
    end
    packages << [archive, gem_spec, entry]
  end
end
seen_archives = {}
packages = packages.reject do |archive, spec, _|
  key = [spec.name, spec.version, Digest::SHA512.file(archive).hexdigest]
  duplicate = seen_archives.key?(key)
  seen_archives[key] = true
  duplicate
end
if (roots = specification["roots"])
  candidates = packages.group_by { |_, spec, _| spec.name }
  selected = {}
  visit = lambda do |name|
    return if selected.key?(name)
    if intrinsics.key?(name)
      selected[name] = true
      intrinsics.fetch(name).fetch("dependencies", []).each do |dependency|
        child = dependency.fetch("name")
        visit.call(child) if candidates.key?(child) || intrinsics.key?(child)
      end
      next
    end
    raise "missing RubyGems projection root #{name}" unless candidates.key?(name)
    selected[name] = true
    candidates.fetch(name).each do |_, spec, _|
      spec.runtime_dependencies.each { |dependency| visit.call(dependency.name) if candidates.key?(dependency.name) || intrinsics.key?(dependency.name) }
    end
  end
  roots.each { |name| visit.call(name) }
  packages.delete_if { |_, spec, _| !selected.key?(spec.name) }
  intrinsics.delete_if { |name, _| !selected.key?(name) }
end
duplicates = Hash[packages.group_by { |_, spec| spec.name }.select { |_, values| values.size > 1 }.to_a]
raise "multiple gem versions need an explicit projection root: #{duplicates.keys.join(', ')}" unless duplicates.empty?
suffix = specification.fetch("identity").gsub(/[^a-zA-Z0-9]/, "").downcase
raise "missing Nix producer identity" if suffix.empty?
# Hash the reachable native graph, so independent producers can share an
# identical prepared dependency without coupling its version to unrelated roots.
raise "Ruby SDK dependency is also supplied as an independent gem" if packages.any? { |_, spec, _| intrinsics.key?(spec.name) }
by_name = Hash[packages.map { |archive, spec, provided| [spec.name, [archive, spec, provided]] }]
fingerprints = {}
versions = Hash[packages.map do |archive, spec, provided|
  if provided
    [spec.name, spec.version.to_s]
  else
    reachable = {}
    visit = lambda do |name|
      return if reachable.key?(name)
      if intrinsics.key?(name)
        entry = intrinsics.fetch(name)
        reachable[name] = [nil, nil, entry]
        entry.fetch("dependencies", []).each do |dependency|
          child = dependency.fetch("name")
          visit.call(child) if by_name.key?(child) || intrinsics.key?(child)
        end
      else
        item = by_name.fetch(name)
        reachable[name] = item
        item[1].runtime_dependencies.each { |dependency| visit.call(dependency.name) if by_name.key?(dependency.name) || intrinsics.key?(dependency.name) }
      end
    end
    visit.call(spec.name)
    graph = reachable.keys.sort.map do |name|
      item_archive, item_spec, item_provided = reachable.fetch(name)
      next [name, "ruby-sdk", item_provided] unless item_spec
      seed = item_provided ? item_provided.fetch("integrity") : specification.fetch("archiveIdentities", {}).fetch(item_archive, suffix)
      [name, item_spec.version.to_s, item_spec.platform.to_s, seed, item_spec.runtime_dependencies.map { |dependency| [dependency.name, dependency.requirement.to_s] }.sort]
    end
    sdk_dependencies = reachable.values.map { |_, value, provided| provided unless value }.select { |entry| entry }
    identity_payload = [specification.fetch("projectorIdentity", "rubygems-v1"), graph, sdk_dependencies]
    if version_scheme == PurifierRubyGemsVersionScheme::NUMERIC
      identity_payload = [version_scheme, native_sdk_identity, identity_payload]
    end
    fingerprint = Digest::SHA256.hexdigest(PurifierRubyGemsCodec.json(identity_payload))
    fingerprints[spec.name] = fingerprint
    [spec.name, PurifierRubyGemsVersionScheme.version(spec.version.to_s, fingerprint, version_scheme)]
  end
end]

intrinsics.each { |name, entry| versions[name] = entry.fetch("version") }
FileUtils.mkdir_p(File.join(destination, "gems"))
FileUtils.mkdir_p(File.join(destination, "quick", "Marshal.4.8"))
entries = []
index_entries = []
packages.each do |archive, original, provided|
  Dir.mktmpdir("rubygems-projection-") do |directory|
    package = Gem::Package.new(archive)
    package.extract_files(directory) unless provided
    spec = original.dup
    spec.version = versions.fetch(original.name)
    spec.dependencies.map! do |dependency|
      next dependency if provided
      next dependency unless dependency.type == :runtime && versions.key?(dependency.name)
      # Native initialization keeps both the current and legacy serialized
      # requirements consistent for older RubyGems consumers.
      pinned = Gem::Dependency.new(dependency.name, "= #{versions.fetch(dependency.name)}", dependency.type)
      if dependency.respond_to?(:prerelease?) && pinned.respond_to?(:prerelease=)
        pinned.prerelease = dependency.prerelease?
      end
      pinned
    end
    unless provided
      seen_sdk = {}
      pin_sdk_children = lambda do |name|
        return if seen_sdk[name] || !intrinsics.key?(name)
        seen_sdk[name] = true
        intrinsics.fetch(name).fetch("dependencies", []).each do |dependency|
          child = dependency.fetch("name")
          if versions.key?(child)
            requirement = Gem::Requirement.new(dependency.fetch("requirement"))
            unless requirement.satisfied_by?(Gem::Version.new(versions.fetch(child)))
              raise "Ruby SDK dependency #{name} requires #{child} #{requirement}, incompatible Nix input #{versions.fetch(child)}"
            end
            spec.add_runtime_dependency(child, "= #{versions.fetch(child)}") unless spec.runtime_dependencies.any? { |value| value.name == child }
            pin_sdk_children.call(child)
          end
        end
      end
      spec.runtime_dependencies.map(&:name).each { |name| pin_sdk_children.call(name) }
    end
    # Original signatures describe different bytes after metadata projection.
    spec.cert_chain = [] unless provided
    filename = provided ? File.basename(archive) : Dir.chdir(directory) { Gem::Package.build(spec) }
    source_archive = provided ? archive : File.join(directory, filename)
    FileUtils.cp(source_archive, File.join(destination, "gems", filename))
    quick = File.join(destination, "quick", "Marshal.4.8", "#{spec.original_name}.gemspec.rz")
    File.open(quick, "wb") { |file| file.write(Zlib::Deflate.deflate(Marshal.dump(spec))) } unless ENV["PURIFIER_RUBYGEMS_SEPARATE_INDEX"] == "1"
    entry = { "name" => spec.name, "version" => spec.version.to_s,
                 "sourceVersion" => provided ? provided.fetch("sourceVersion") : original.version.to_s, "platform" => spec.platform.to_s,
                 "integrity" => "sha512-#{Base64.encode64(Digest::SHA512.file(source_archive).digest).delete("\n")}",
                 "archive" => "gems/#{filename}" }
    index_entries << entry
    if provided
      entry = provided.dup
    elsif version_scheme == PurifierRubyGemsVersionScheme::NUMERIC
      entry["versionScheme"] = version_scheme
      entry["nativeSdkIdentity"] = native_sdk_identity
      entry["versionFingerprint"] = fingerprints.fetch(spec.name)
    end
    entries << entry
  end
end
unless ENV["PURIFIER_RUBYGEMS_SEPARATE_INDEX"] == "1"
specs = index_entries.map { |entry| [entry.fetch("name"), Gem::Version.new(entry.fetch("version")), entry.fetch("platform")] }.sort
{
  "specs" => specs.reject { |_, version, _| version.prerelease? },
  "latest_specs" => specs.reject { |_, version, _| version.prerelease? }.group_by { |name, _, platform| [name, platform] }.values.map { |values| values.max_by { |_, version, _| version } }.sort,
  "prerelease_specs" => specs.select { |_, version, _| version.prerelease? },
}.each do |kind, values|
  Zlib::GzipWriter.open(File.join(destination, "#{kind}.4.8.gz")) do |writer|
    # Older zlib bindings treat zero as "use the current time".
    writer.mtime = 1
    writer.write(Marshal.dump(values))
  end
end
end
FileUtils.mkdir_p(File.dirname(catalog_path))
File.open(catalog_path, "wb") { |file| file.write(PurifierRubyGemsCodec.json({ "format" => "rubygems", "packages" => entries, "intrinsics" => intrinsics.values.sort_by { |entry| entry.fetch("name") } }) + "\n") }
