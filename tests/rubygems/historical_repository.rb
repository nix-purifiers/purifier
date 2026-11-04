# SPDX-License-Identifier: MIT
# Native codecs, graph pinning, exact reuse and ordinary installation on Ruby 2.5.
require 'rubygems/package'
require 'rbconfig'
require 'json'
require 'digest'
require 'fileutils'
require 'tmpdir'
require 'open3'

raise 'wrong SDK selected' unless RUBY_VERSION == ENV.fetch('EXPECTED_RUBY_VERSION', RUBY_VERSION)
Dir.mktmpdir('historical-rubygems-') do |root|
  archives = []
  %w[historical-b historical-a].each do |name|
    directory = File.join(root, name)
    FileUtils.mkdir_p(File.join(directory, 'lib'))
    body = name.end_with?('b') ? 'HistoricalB=41' : "require 'historical_b'; require 'json'; HistoricalA=HistoricalB+1"
    File.write(File.join(directory, 'lib', name.tr('-', '_') + '.rb'), body + "\n")
    spec = Gem::Specification.new do |s|
      s.name = name; s.version = '1.0.0'; s.authors = ['fixture']; s.summary = 'Historical native codec proof'; s.license = 'MIT'
      s.date = Time.utc(2000, 1, 1)
      s.files = Dir.chdir(directory) { Dir['lib/**/*'] }
      if name.end_with?('a')
        s.add_runtime_dependency('historical-b', '=1.0.0')
        s.add_runtime_dependency('json', '>=0')
      end
    end
    archive = Dir.chdir(directory) { Gem::Package.build(spec) }
    archives << File.join(directory, archive)
  end
  sdk_spec = Gem::Specification.find_by_name('json')
  sdk = { 'name'=>'json', 'version'=>sdk_spec.version.to_s, 'sdk'=>RbConfig::CONFIG.fetch('prefix'),
          'ruby'=>RUBY_VERSION, 'system'=>Gem::Platform.local.to_s, 'dependencies'=>[] }
  origins = Hash[archives.map { |archive| [archive, Digest::SHA256.file(archive).hexdigest] }]
  request = { 'identity'=>'first-producer', 'projectorIdentity'=>'historical-codec-test-v1',
              'archiveIdentities'=>origins, 'archives'=>archives, 'intrinsics'=>[sdk], 'roots'=>['historical-a'] }
  projector = ENV.fetch('RUBYGEMS_PROJECTOR', File.expand_path('../../tools/rubygems_repository.rb', __dir__))
  # In the source checkout this test sits under tests/rubygems.
  projector = File.expand_path('../../../tools/rubygems_repository.rb', __FILE__) unless File.file?(projector)
  project = lambda do |value, name|
    input = File.join(root, name + '.json'); File.write(input, JSON.dump(value))
    repository = File.join(root, name); catalog = File.join(root, name + '-catalog.json')
    raise 'native projection failed' unless system(Gem.ruby, projector, input, repository, catalog)
    [repository, catalog, JSON.parse(File.read(catalog))]
  end
  repository, catalog_path, catalog = project.call(request, 'repository')
  repeat, _, repeated = project.call(request.merge('identity'=>'independent-producer'), 'repeat')
  raise 'independent producers changed graph identity' unless catalog == repeated
  catalog.fetch('packages').each do |entry|
    raise 'repeated archive changed bytes' unless File.binread(File.join(repository, entry.fetch('archive'))) == File.binread(File.join(repeat, entry.fetch('archive')))
  end
  entries = Hash[catalog.fetch('packages').map { |entry| [entry.fetch('name'), entry] }]
  a = Gem::Package.new(File.join(repository, entries.fetch('historical-a').fetch('archive'))).spec
  requirement = a.runtime_dependencies.find { |dependency| dependency.name == 'historical-b' }.requirement
  raise 'dependency was not exactly pinned' unless requirement == Gem::Requirement.new('= ' + entries.fetch('historical-b').fetch('version'))
  raise 'SDK intrinsic was lost' unless catalog.fetch('intrinsics') == [sdk]
  reuse, _, reused = project.call({ 'identity'=>'consumer', 'archives'=>[], 'roots'=>['historical-a'],
    'dependencies'=>[{ 'repository'=>repository, 'catalog'=>catalog_path }] }, 'reuse')
  raise 'provided repository changed catalog' unless catalog == reused
  catalog.fetch('packages').each do |entry|
    raise 'provided archive changed bytes' unless File.binread(File.join(repository, entry.fetch('archive'))) == File.binread(File.join(reuse, entry.fetch('archive')))
  end
  home = File.join(root, 'ordinary')
  environment = { 'GEM_HOME'=>home, 'GEM_PATH'=>[home, Gem.default_dir].join(File::PATH_SEPARATOR) }
  gem_command = File.join(RbConfig::CONFIG.fetch('bindir'), 'gem')
  %w[historical-b historical-a].each do |name|
    archive = File.join(repository, entries.fetch(name).fetch('archive'))
    raise 'ordinary gem install failed' unless system(environment, Gem.ruby, gem_command, 'install', '--local', '--no-document', archive)
  end
  output, status = Open3.capture2(environment, Gem.ruby, '-e', "require 'historical_a'; print HistoricalA")
  raise 'ordinary execution failed' unless status.success? && output == '42'
  puts "PASS Ruby #{RUBY_VERSION}: native graph pinning, SDK intrinsic, reproducible archives, exact provided reuse, ordinary install and execution"
end
