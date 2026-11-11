# SPDX-License-Identifier: MIT
# Separate schema; deliberately compatible with original Ruby182/Gem094.
require "json"
require "digest/sha2"
require "base64"
module PurifierRubyGemsConsumerSDKContract
  PROFILE = "ruby182-rubygems094-v1"
  ARCHIVES = {
    "ruby"=>"sha256-NM+VeRMjyW3JLGcsFtqu9p8AoLpp4cQ7q4k644t+6z4=",
    "rubygems"=>"sha256-PKDlSnEpnxOvBPpKvctRJI8wJXEu/hk+h9sxqkHUQXs=",
    "sources"=>"sha256-ge7BFLWjo6h8NOwaBeEVKuD+DdWuUcsRg+r7dN6MiQQ=",
    "json"=>"sha256-N5hS1KiOaLWGBaP7rVxtfDKaTn6RsiGj1LB3xjzcZP4=",
    "bundler"=>"sha256-Ru5Nqt2nlsHpQztFAV/0P2fqR8jPEObyJP9dhxJtMwI="
  }
  class UniqueObject < Hash
    def []=(key, value)
      raise "duplicate consumer SDK field" if key?(key)
      super
    end
  end
  def self.exact!(value, keys)
    raise "invalid consumer SDK fields" unless value.is_a?(Hash) && value.keys.sort == keys.sort
  end
  def self.canonical(value)
    case value
    when Hash
      "{" + value.keys.sort.map { |key| canonical(key) + ":" + canonical(value[key]) }.join(",") + "}"
    when Array
      "[" + value.map { |item| canonical(item) }.join(",") + "]"
    else
      JSON.generate(value).gsub("\\/", "/")
    end
  end
  def self.digest!(value)
    raise "invalid consumer SDK digest" unless value.is_a?(String) && value =~ /\Asha256-[A-Za-z0-9+\/]{43}=\z/ && "sha256-" + [value.sub(/\Asha256-/, "").unpack("m")[0]].pack("m").delete("\n") == value
  end
  def self.path!(value)
    raise "invalid consumer SDK path" unless value.is_a?(String) && value =~ /\A\/nix\/store\/[a-z0-9]{32}-[A-Za-z0-9+._?=-]+(?:\/[A-Za-z0-9+._?=-]+)*\z/
    raise "consumer SDK path is missing" unless File.exist?(value)
    raise "consumer SDK path is a symlink" if File.symlink?(value)
  end
  def self.hex!(value)
    raise "invalid consumer SDK SHA256" unless value.is_a?(String) && value =~ /\A[0-9a-f]{64}\z/
  end
  def self.hash_file(path)
    "sha256-" + [Digest::SHA256.digest(File.open(path,"rb"){|file|file.read})].pack("m").delete("\n")
  end
  def self.validate!(value)
    exact!(value, %w[format schemaVersion profile sdk observation components compiler nativeBuild closure])
    raise "unsupported consumer SDK schema" unless value["format"] == "rubygems-native-consumer-sdk" && value["schemaVersion"].is_a?(Integer) && value["schemaVersion"] == 1 && value["profile"] == PROFILE
    path!(value["sdk"])
    rows = value["closure"]
    raise "invalid consumer SDK closure" unless rows.is_a?(Array) && rows.size.between?(1,4096)
    paths = rows.map do |row|
      exact!(row,%w[path narHash]);path!(row["path"]);digest!(row["narHash"]);row["path"]
    end
    raise "consumer closure needs store roots" unless paths.all?{|path|path =~ /\A\/nix\/store\/[a-z0-9]{32}-[^\/]+\z/}
    raise "noncanonical consumer SDK closure" unless paths == paths.sort.uniq && paths.include?(value["sdk"])
    inside = lambda { |path| paths.any? { |root| path == root || path.index(root + "/") == 0 } }
    observation = value["observation"]
    exact!(observation,%w[ruby patchlevel abi platform executable interpreterHash rubygemsReport rubyLibrary rubygemsLibrary installed specificationFiles nativeLibraries bundlerLoaded])
    raise "unsupported consumer runtime" unless observation["ruby"] == "1.8.2" && observation["patchlevel"].nil? && observation["abi"] == "1.8" && observation["platform"] == "x86_64-linux" && observation["bundlerLoaded"] == false && observation["rubygemsReport"] == {"name"=>"Gem::RubyGemsVersion","value"=>"0.9.4"}
    %w[executable rubyLibrary rubygemsLibrary].each do |key|
      path!(observation[key]);raise "consumer runtime escapes closure" unless inside.call(observation[key])
    end
    digest!(observation["interpreterHash"])
    raise "consumer interpreter changed" unless hash_file(observation["executable"]) == observation["interpreterHash"]
    components = value["components"]
    expected = {"ruby"=>"1.8.2","rubygems"=>"0.9.4","sources"=>"0.0.1","json"=>"1.1.3","bundler"=>"0.3.1"}
    raise "invalid consumer components" unless components.is_a?(Array) && components.size == 5 && components.map{|item|item["name"]} == expected.keys.sort
    components.each do |item|
      exact!(item,%w[name version archive archiveHash library libraryHash role])
      raise "consumer component version differs" unless expected[item["name"]] == item["version"]
      raise "consumer component role differs" unless item["role"] == (item["name"] == "bundler" ? "incidental-unloaded-client" : "consumer-component")
      %w[archive library].each do |key|
        path!(item[key]);raise "consumer component escapes closure" unless inside.call(item[key])
      end
      digest!(item["archiveHash"]);digest!(item["libraryHash"])
      raise "consumer archive is not the original profile artifact" unless ARCHIVES[item["name"]] == item["archiveHash"]
      raise "consumer archive changed" unless File.file?(item["archive"]) && hash_file(item["archive"]) == item["archiveHash"]
    end
    installed = observation["installed"]
    raise "consumer installed set differs" unless installed.is_a?(Array) && installed.size == 3 && installed.map{|item|item["name"]} == %w[bundler json sources]
    installed.each do |item|
      exact!(item,%w[name version library]);component=components.detect{|entry|entry["name"] == item["name"]}
      raise "installed consumer artifact differs" unless item["version"] == component["version"] && item["library"] == component["library"]
    end
    specification_files=observation["specificationFiles"]
    raise "consumer specification set differs" unless specification_files.is_a?(Array) && specification_files.size == 3 && specification_files.map{|item|item["path"]} == specification_files.map{|item|item["path"]}.sort.uniq
    specification_files.each do |item|
      exact!(item,%w[path sha256]);path!(item["path"]);hex!(item["sha256"])
      raise "consumer specification changed" unless inside.call(item["path"]) && Digest::SHA256.hexdigest(File.open(item["path"],"rb"){|file|file.read}) == item["sha256"]
    end
    expected_specifications=installed.map do |item|
      File.join(File.dirname(File.dirname(item["library"])),"specifications",item["name"]+"-"+item["version"]+".gemspec")
    end.sort
    raise "consumer specification coordinates differ" unless specification_files.map{|item|item["path"]} == expected_specifications
    %w[ruby rubygems].each do |name|
      raise "consumer runtime library differs" unless observation[name+"Library"] == components.detect{|item|item["name"] == name}["library"]
    end
    natives = observation["nativeLibraries"]
    raise "consumer native library set differs" unless natives.is_a?(Array) && natives.size == 1
    natives.each do |item|
      exact!(item,%w[path sha256]);path!(item["path"]);hex!(item["sha256"])
      json_root=components.detect{|entry|entry["name"]=="json"}["library"]
      raise "native parser differs" unless item["path"].index(json_root + "/") == 0 && item["path"] =~ /\/json\/ext\/parser.so\z/ && Digest::SHA256.hexdigest(File.open(item["path"],"rb"){|file|file.read}) == item["sha256"]
    end
    exact!(value["compiler"],%w[path narHash]);path!(value["compiler"]["path"]);digest!(value["compiler"]["narHash"])
    raise "compiler escapes closure" unless inside.call(value["compiler"]["path"])
    raise "compiler closure hash differs" unless rows.any?{|row|row["path"]==value["compiler"]["path"] && row["narHash"]==value["compiler"]["narHash"]}
    build=value["nativeBuild"]
    exact!(build,%w[derivation originalDerivation derivationSha256 compilerDerivation originalCompilerDerivation compilerDerivationSha256 buildCommandSha256 nativeBuildInputs outputs])
    %w[derivation compilerDerivation].each do |key|
      path!(build[key]);hex!(build[key+"Sha256"])
      raise "native build provenance changed" unless inside.call(build[key]) && Digest::SHA256.hexdigest(File.open(build[key],"rb"){|file|file.read}) == build[key+"Sha256"]
    end
    hex!(build["buildCommandSha256"])
    %w[originalDerivation originalCompilerDerivation].each do |key|
      raise "invalid original derivation coordinate" unless build[key].is_a?(String) && build[key] =~ /\A\/nix\/store\/[a-z0-9]{32}-[A-Za-z0-9+._?=-]+\.drv\z/
    end
    raise "native compiler is not bound" unless build["nativeBuildInputs"].is_a?(Array) && build["nativeBuildInputs"].size.between?(1,128) && build["nativeBuildInputs"].uniq==build["nativeBuildInputs"] && build["nativeBuildInputs"].include?(value["compiler"]["path"])
    build["nativeBuildInputs"].each{|path|path!(path);raise "native input escapes closure" unless inside.call(path)}
    raise "native output differs" unless build["outputs"].is_a?(Array) && build["outputs"].size==1 && installed.all?{|item|item["library"].index(build["outputs"][0]+"/")==0}
    path!(build["outputs"][0]);raise "native output escapes closure" unless inside.call(build["outputs"][0])
    value
  end
  def self.read!(path, identity = nil)
    raw=File.open(path,"rb"){|file|file.read(1048577)}
    raise "consumer SDK attestation exceeds bound" if raw.length > 1048576
    value=JSON.parse(raw,:object_class=>UniqueObject)
    validate!(value)
    bytes=canonical(value)
    raise "noncanonical consumer SDK attestation" unless raw == bytes+"\n"
    actual="sha256-"+[Digest::SHA256.digest(bytes)].pack("m").delete("\n")
    raise "consumer SDK identity differs" if identity && identity != actual
    value
  end
end
