# SPDX-License-Identifier: MIT
# Private observation serializer; does not add APIs to the original SDK.
module PurifierRubyGems0811Probe
  def self.canonical(value)
    case value
    when Hash
      raise "non-string observation key" unless value.keys.all? { |key| key.is_a?(String) }
      '{' + value.keys.sort.map { |key| canonical(key) + ':' + canonical(value[key]) }.join(',') + '}'
    when Array
      '[' + value.map { |item| canonical(item) }.join(',') + ']'
    when String
      '"' + value.unpack('C*').map { |byte|
        if byte == 34 then '\\"'
        elsif byte == 92 then '\\\\'
        elsif byte == 8 then '\\b'
        elsif byte == 9 then '\\t'
        elsif byte == 10 then '\\n'
        elsif byte == 12 then '\\f'
        elsif byte == 13 then '\\r'
        elsif byte >= 32 && byte <= 126 then byte.chr
        elsif byte < 32 || byte == 127 then sprintf('\\u%04x', byte)
        else raise 'non-ASCII observation string'
        end
      }.join + '"'
    when Integer then value.to_s
    when TrueClass then 'true'
    when FalseClass then 'false'
    when NilClass then 'null'
    else raise 'unsupported observation type'
    end
  end
  def self.observe
    require 'rubygems'
    Gem.manage_gems
    require 'pathname'
    require 'digest/sha2'
    raise 'unsupported original0811 runtime' unless RUBY_VERSION == '1.8.0' && !defined?(RUBY_PATCHLEVEL) && RUBY_PLATFORM == 'i686-linux-gnu' && Gem::RubyGemsVersion == '0.8.11'
    raise 'unexpected SDK activation API' if defined?(Bundler) || Gem.respond_to?(:loaded_specs) || Kernel.instance_methods.map { |name| name.to_s }.include?('gem')
    require_gem 'sources', '= 0.0.1'
    require 'sources'
    real = lambda { |path| Pathname.new(path).realpath.to_s }
    executable = real.call(File.readlink('/proc/self/exe'))
    elf = File.open(executable, 'rb') { |file| file.read(20) }
    raise 'native ELF32 i386 required' unless elf[0,4] == "\177ELF" && elf[4] == 1 && elf[5] == 1 && elf[18,2].unpack('v')[0] == 3 && ['pointer'].pack('p').size == 4
    gem_file = $LOAD_PATH.map { |path| File.join(path, 'rubygems.rb') }.detect { |path| File.file?(path) }
    raise 'missing native RubyGems library' unless gem_file
    installed = []
    Gem.source_index.each do |name, spec|
      installed << {'name'=>spec.name, 'version'=>spec.version.to_s, 'library'=>real.call(spec.full_gem_path)}
    end
    raise 'unexpected installed components' unless installed.size == 1 && installed[0]['name'] == 'sources' && installed[0]['version'] == '0.0.1'
    specifications = Gem.path.map { |path| Dir[File.join(path, 'specifications', '*.gemspec')] }.flatten.uniq.sort
    raise 'unexpected installed specifications' unless specifications.size == 1 && specifications.all? { |path| File.file?(path) && !File.symlink?(path) }
    hash = lambda { |path| Digest::SHA256.hexdigest(File.open(path, 'rb') { |file| file.read }) }
    {'ruby'=>RUBY_VERSION, 'patchlevel'=>nil, 'abi'=>Config::CONFIG['ruby_version'], 'platform'=>RUBY_PLATFORM,
     'nixSystem'=>'i686-linux', 'pointerBytes'=>4, 'elfClass'=>32, 'elfMachine'=>3,
     'executable'=>executable, 'interpreterSha256'=>hash.call(executable),
     'rubygemsReport'=>{'name'=>'Gem::RubyGemsVersion','value'=>Gem::RubyGemsVersion},
     'rubyLibrary'=>real.call(Config::CONFIG['prefix']), 'rubygemsLibrary'=>real.call(File.dirname(File.dirname(gem_file))),
     'installed'=>installed, 'specificationFiles'=>specifications.map { |path| {'path'=>real.call(path),'sha256'=>hash.call(path)} },
     'bundlerLoaded'=>false}
  end
end
if __FILE__ == $0
  puts PurifierRubyGems0811Probe.canonical(PurifierRubyGems0811Probe.observe)
end
