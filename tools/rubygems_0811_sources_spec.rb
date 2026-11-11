# SPDX-License-Identifier: MIT
# Separate original-native metadata verification, never a consumer SDK shim.
require 'rubygems'
Gem.manage_gems
raise 'unsupported original0811 metadata runtime' unless RUBY_VERSION=='1.8.0' && Gem::RubyGemsVersion=='0.8.11' && RUBY_PLATFORM=='i686-linux-gnu'
raise 'expected original embedded source tree' unless ARGV.length==1
Dir.chdir(ARGV[0]) do
  load './sources.gemspec'
  spec=Gem.sources_spec
  raise 'original bundled sources changed' unless spec.name=='sources' && spec.version.to_s=='0.0.1' && spec.platform.to_s=='ruby' && spec.dependencies.empty? && spec.files==['lib/sources.rb'] && spec.required_ruby_version.to_s=='> 0.0.0' && spec.signing_key.nil? && (spec.cert_chain.nil? || spec.cert_chain.empty?)
  spec.date='1970-01-01'
  raise 'bootstrap metadata date changed' unless spec.date.strftime('%Y-%m-%d')=='1970-01-01'
  STDOUT.write(spec.to_ruby)
end
