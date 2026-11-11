# SPDX-License-Identifier: MIT
# Host-side0811 contract; never loaded into or injected into the original SDK.
require 'json'
require 'digest/sha2'
module PurifierRubyGems0811Contract
  PROFILE = 'ruby180-rubygems0811-i686-v1'
  ARCHIVES = {'ruby'=>'sha256-EVxf4KFXCavRtkNRqhvtnAMNHz13ytPy8rULNwTCAfE=', 'rubygems'=>'sha256-x+2bn1DqzpXa7EkXRM0yLnTAZg3QAZ85n1TIW7cCtf8='}
  class UniqueObject < Hash
    def []=(key,value)
      raise 'duplicate0811 attestation key' if key?(key)
      super
    end
  end
  def self.exact!(value,fields)
    raise 'invalid0811 attestation fields' unless value.is_a?(Hash) && value.keys.sort == fields.split.sort
  end
  def self.canonical(value)
    case value
    when Hash
      '{'+value.keys.sort.map { |key| canonical(key)+':'+canonical(value[key]) }.join(',')+'}'
    when Array then '['+value.map { |item| canonical(item) }.join(',')+']'
    when String
      raise 'nonASCII0811 attestation string' unless value.ascii_only?
      JSON.generate(value).gsub('\\/','/').gsub("\u007f",'\\u007f')
    when Integer, TrueClass, FalseClass, NilClass then JSON.generate(value)
    else raise 'unsupported0811 attestation type'
    end
  end
  def self.hex!(value)
    raise 'invalid0811 hash' unless value.is_a?(String) && value.match?(/\A[0-9a-f]{64}\z/)
  end
  def self.digest!(value)
    raise 'invalid0811 digest' unless value.is_a?(String) && value.match?(/\Asha256-[A-Za-z0-9+\/]{43}=\z/) && 'sha256-'+[value.sub(/\Asha256-/,'').unpack1('m0')].pack('m0') == value
  end
  def self.hash_file(path)
    'sha256-'+[Digest::SHA256.file(path).digest].pack('m0')
  end
  def self.read!(path,identity=nil)
    raw=File.binread(path,1048577)
    raise 'oversized0811 attestation' if raw.bytesize>1048576
    value=JSON.parse(raw,object_class:UniqueObject)
    exact!(value,'format schemaVersion profile serializerVersion sdk underlyingSdk observation components bundledSources compiler provenance stdenvSetup closure bootstrapPolicy')
    raise 'unsupported0811 schema' unless value['format']=='rubygems-native-consumer-sdk-0811-i686' && value['schemaVersion'].instance_of?(Integer) && value['schemaVersion']==1 && value['profile']==PROFILE && value['serializerVersion']=='ascii-primitives-v1'
    policy=value['bootstrapPolicy']
    exact!(policy,'format schemaVersion date timezone generatedCache')
    raise 'unsupported0811 bootstrap policy' unless policy=={'format'=>'original0811-sources-bootstrap','schemaVersion'=>1,'date'=>'1970-01-01','timezone'=>'UTC','generatedCache'=>'absent'} && policy['schemaVersion'].instance_of?(Integer)
    bytes=canonical(value)
    raise 'noncanonical0811 attestation' unless raw==bytes+"\n"
    actual='sha256-'+[Digest::SHA256.digest(bytes)].pack('m0')
    raise '0811 attestation identity differs' if identity && identity!=actual
    rows=value['closure']
    raise 'invalid0811 closure' unless rows.is_a?(Array) && rows.size.between?(1,4096)
    paths=rows.map { |row| exact!(row,'path narHash');digest!(row['narHash']);row['path'] }
    raise 'noncanonical0811 closure' unless paths==paths.sort.uniq && paths.all? { |p| p.is_a?(String) && p.match?(/\A\/nix\/store\/[a-z0-9]{32}-[A-Za-z0-9+._?=-]+\z/) && File.realpath(p)==p }
    physical=lambda { |p| raise '0811 path escapes actual closure' unless p.is_a?(String) && paths.any? { |root| p==root || p.start_with?(root+'/') } && File.realpath(p)==p }
    %w[sdk underlyingSdk].each { |key| physical.call(value[key]);raise '0811 SDK needs store root' unless paths.include?(value[key]) }
    o=value['observation']
    exact!(o,'ruby patchlevel abi platform nixSystem pointerBytes elfClass elfMachine executable interpreterSha256 rubygemsReport rubyLibrary rubygemsLibrary installed specificationFiles bundlerLoaded')
    expected={'ruby'=>'1.8.0','patchlevel'=>nil,'abi'=>'1.8','platform'=>'i686-linux-gnu','nixSystem'=>'i686-linux','pointerBytes'=>4,'elfClass'=>32,'elfMachine'=>3,'bundlerLoaded'=>false,'rubygemsReport'=>{'name'=>'Gem::RubyGemsVersion','value'=>'0.8.11'}}
    raise '0811 native runtime differs' unless expected.all? { |key,v| o[key].is_a?(v.class) && o[key]==v }
    %w[executable rubyLibrary rubygemsLibrary].each { |key| physical.call(o[key]) }
    hex!(o['interpreterSha256'])
    elf=File.binread(o['executable'],20)
    raise '0811 actual interpreter differs' unless Digest::SHA256.file(o['executable']).hexdigest==o['interpreterSha256'] && elf[0,6]=="\x7fELF\x01\x01" && elf[18,2].unpack1('v')==3
    installed=o['installed'];specs=o['specificationFiles']
    raise '0811 installed set differs' unless installed.is_a?(Array) && installed.size==1 && specs.is_a?(Array) && specs.size==1
    exact!(installed[0],'name version library');exact!(specs[0],'path sha256')
    raise '0811 sources coordinate differs' unless installed[0]['name']=='sources' && installed[0]['version']=='0.0.1' && specs[0]['path']==File.join(File.dirname(File.dirname(installed[0]['library'])),'specifications/sources-0.0.1.gemspec')
    physical.call(installed[0]['library']);physical.call(specs[0]['path']);hex!(specs[0]['sha256'])
    raise '0811 specification changed' unless Digest::SHA256.file(specs[0]['path']).hexdigest==specs[0]['sha256']
    components=value['components']
    raise '0811 component set differs' unless components.is_a?(Array) && components.map { |c| c['name'] }==%w[ruby rubygems]
    components.each do |c|
      exact!(c,'name version archive archiveHash library libraryHash');%w[archive library].each { |k| physical.call(c[k]) };digest!(c['archiveHash']);digest!(c['libraryHash'])
      raise '0811 original component differs' unless c['version']=={'ruby'=>'1.8.0','rubygems'=>'0.8.11'}[c['name']] && c['archiveHash']==ARCHIVES[c['name']] && hash_file(c['archive'])==c['archiveHash'] && c['library']==o[c['name']+'Library']
    end
    bundled=value['bundledSources']
    exact!(bundled,'library libraryHash originalSources definitionSha256 payload payloadSha256 specification specificationSha256 cachePath cacheAbsent')
    %w[library originalSources payload specification].each { |k| physical.call(bundled[k]) }
    digest!(bundled['libraryHash'])
    %w[definitionSha256 payloadSha256 specificationSha256].each { |k| hex!(bundled[k]) }
    definition=File.join(bundled['originalSources'],'sources.gemspec')
    original_payload=File.join(bundled['originalSources'],'lib/sources.rb')
    physical.call(definition);physical.call(original_payload)
    raise '0811 original sources definition changed' unless bundled['definitionSha256']=='8b87e7c6fbedd816acb3d9ecbbd60581ab8d1220f371ecb5e72bf5536651ee45' && Digest::SHA256.file(definition).hexdigest==bundled['definitionSha256']
    raise '0811 original sources payload changed' unless bundled['payloadSha256']=='0090abe7226ae17a24853080b49cc2dd8b36aeaf8d6fea18be543923fa51f2f4' && Digest::SHA256.file(original_payload).hexdigest==bundled['payloadSha256'] && Digest::SHA256.file(bundled['payload']).hexdigest==bundled['payloadSha256']
    raise '0811 bundled sources coordinate differs' unless bundled['library']==installed[0]['library'] && bundled['payload']==File.join(bundled['library'],'lib/sources.rb') && bundled['specification']==specs[0]['path'] && bundled['specificationSha256']==specs[0]['sha256'] && bundled['specificationSha256']=='58b33227c6604b4670a3bdf4aa37c5e742b9ff9acbeece78f56eabce49a7361e'
    raise '0811 transient generated cache retained' unless bundled['cacheAbsent']==true && bundled['cachePath']==File.join(o['rubygemsLibrary'],'gems/cache/sources-0.0.1.gem') && !File.exist?(bundled['cachePath']) && !File.symlink?(bundled['cachePath'])
    compiler=value['compiler'];exact!(compiler,'path narHash versionOutput target');physical.call(compiler['path']);digest!(compiler['narHash'])
    raise '0811 compiler differs' unless compiler['target']=='i686-pc-linux-gnu' && compiler['versionOutput'].is_a?(String) && compiler['versionOutput'].lines.first.chomp == 'gcc (GCC) 4.8.3' && rows.any? { |r| r['path']==compiler['path'] && r['narHash']==compiler['narHash'] }
    provenance=value['provenance'];exact!(provenance,'runtimeBuild stdenvBuild compilerBuild sdkBuild')
    provenance.each_value do |p|
      exact!(p,'captured original sha256');physical.call(p['captured']);hex!(p['sha256'])
      raise '0811 build provenance changed' unless p['original'].is_a?(String) && p['original'].match?(/\A\/nix\/store\/[a-z0-9]{32}-[A-Za-z0-9+._?=-]+\.drv\z/) && Digest::SHA256.file(p['captured']).hexdigest==p['sha256']
    end
    setup=value['stdenvSetup'];exact!(setup,'path sha256');physical.call(setup['path']);hex!(setup['sha256'])
    raise '0811 stdenv setup changed' unless Digest::SHA256.file(setup['path']).hexdigest==setup['sha256']
    value
  end
end
