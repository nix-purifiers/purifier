# SPDX-License-Identifier: MIT
# Separate original consumer observation; no Bundler activation or SDK patch.
module PurifierRubyGemsConsumerProbe
  def self.observe
    require "rubygems"
    require "pathname"
    require "digest/sha2"
    raise "unsupported consumer SDK" unless RUBY_VERSION == "1.8.2" && !defined?(RUBY_PATCHLEVEL) && Gem::RubyGemsVersion == "0.9.4"
    raise "incidental Bundler was activated" if defined?(Bundler)
    require "sources"
    gem "json", "= 1.1.3"
    require "json"
    raise "native JSON parser is missing" unless JSON.parser == JSON::Ext::Parser && JSON.parse('{"answer":42}')["answer"] == 42
    real = lambda { |path| Pathname.new(path).realpath.to_s }
    config = Config::CONFIG
    executable = real.call("/proc/self/exe")
    gem_file = $LOAD_PATH.map { |path| File.join(path, "rubygems.rb") }.detect { |path| File.file?(path) }
    raise "native RubyGems library missing" unless gem_file
    installed = []
    specification_files = Gem.path.map { |path| Dir[File.join(path, "specifications", "*.gemspec")] }.flatten.uniq.sort
    raise "unexpected installed SDK specification set" unless specification_files.size == 3 && specification_files.all? { |path| File.file?(path) && !File.symlink?(path) }
    Gem::SourceIndex.from_installed_gems.each do |name, spec|
      installed << {"name"=>spec.name, "version"=>spec.version.to_s, "library"=>real.call(spec.full_gem_path)}
    end
    parsers = File.readlines("/proc/self/maps").map { |line| line.split.last }.uniq.select { |path| path && path =~ /json\/ext\/parser.so$/ }
    json_root = real.call(Gem.loaded_specs["json"].full_gem_path)
    raise "native parser origin differs" unless parsers.size == 1 && real.call(parsers.first).index(json_root + "/") == 0
    return {"ruby"=>RUBY_VERSION,"patchlevel"=>nil,"abi"=>config["ruby_version"],"platform"=>RUBY_PLATFORM,"executable"=>executable,"interpreterHash"=>"sha256-"+[Digest::SHA256.digest(File.open(executable,"rb"){|file|file.read})].pack("m").delete("\n"),"rubygemsReport"=>{"name"=>"Gem::RubyGemsVersion","value"=>Gem::RubyGemsVersion},"rubyLibrary"=>real.call(config["prefix"]),"rubygemsLibrary"=>real.call(File.dirname(File.dirname(gem_file))),"installed"=>installed.sort_by{|entry|entry["name"]},"specificationFiles"=>specification_files.map{|path|{"path"=>real.call(path),"sha256"=>Digest::SHA256.hexdigest(File.open(path,"rb"){|file|file.read})}},"nativeLibraries"=>parsers.map{|path|{"path"=>real.call(path),"sha256"=>Digest::SHA256.hexdigest(File.open(path,"rb"){|file|file.read})}},"bundlerLoaded"=>false}
  end
end
if __FILE__ == $0
  observation = PurifierRubyGemsConsumerProbe.observe
  puts JSON.generate(observation)
end
