{ pkgs, olderRubySource }:
let
  ruby = import ./runtime.nix { inherit pkgs olderRubySource; };
  archive = pkgs.fetchurl {
    url = "https://rubygems.org/downloads/rubygems-update-0.8.11.gem";
    hash = "sha256-x+2bn1DqzpXa7EkXRM0yLnTAZg3QAZ85n1TIW7cCtf8=";
  };
  gemBase =
    pkgs.runCommand "ruby180-i686-rubygems0811-original-installed"
      {
        nativeBuildInputs = [ pkgs.ruby ];
        bootstrapPolicyVersion = "1";
        bootstrapDate = "1970-01-01";
        TZ = "UTC";
      }
      ''
          export HOME="$TMPDIR/home" GEM_HOME="$TMPDIR/gems" GEM_PATH="$TMPDIR/gems"
          mkdir -p "$HOME" "$GEM_HOME"
          ruby -rfileutils -rrubygems/package -e 'Gem::Package.new(ARGV[0]).extract_files("source")' ${archive}
          cd source
          unset RUBYOPT RUBYLIB
          ${ruby}/bin/ruby setup.rb config --prefix="$out" --rbdir="$out/lib" --sodir="$out/lib" --bindir="$out/bin"
          ${ruby}/bin/ruby setup.rb setup
          ${ruby}/bin/ruby -Ilib bin/gem --version
          ${ruby}/bin/ruby -Ilib -e 'require "rubygems";Gem.manage_gems;Dir.chdir("pkgs/sources"){load "sources.gemspec";s=Gem.sources_spec;raise unless s.required_ruby_version.satisfied_by?(Gem::Version.new(RUBY_VERSION));raise unless s.dependencies.empty?;raise unless ["ruby",RUBY_PLATFORM].include?(s.platform.to_s);puts "BUNDLED-SOURCE-MINIMUM|#{s.name}|#{s.version}|#{s.required_ruby_version}|#{s.platform}|#{s.dependencies.size}"};raise if defined?(RUBY_PATCHLEVEL);puts "ORIGINAL-SOURCE-SDK|#{RUBY_VERSION}|#{Gem::RubyGemsVersion}"'
          export GEM_HOME="$out/gems" GEM_PATH="$out/gems"
          mkdir -p "$GEM_HOME"
          ${ruby}/bin/ruby -Ilib -e '
          require "rubygems";Gem.manage_gems;require "digest/sha2"
          identity=nil;expected=nil
          Dir.chdir("pkgs/sources") do
            load "sources.gemspec"
            spec=Gem.sources_spec
            spec.date="1970-01-01"
            identity=spec.object_id;expected=spec.to_ruby
          end
          $0="./setup.rb"
          load "./setup.rb"
          raise unless Gem.sources_spec.object_id==identity
          actual=File.open(File.join(ENV["GEM_HOME"],"specifications/sources-0.0.1.gemspec"),"rb"){|f|f.read}
          raise unless actual==expected
          puts "BOOTSTRAP-POLICY|1|1970-01-01|UTC|#{Digest::SHA256.hexdigest(actual)}"
        ' install
        test -f "$out/gems/cache/sources-0.0.1.gem"
        rm -- "$out/gems/cache/sources-0.0.1.gem"
        test ! -e "$out/gems/cache/sources-0.0.1.gem"
          ${ruby}/bin/ruby -I"$out/lib" "$out/bin/gem" --version
      '';
  sdk =
    pkgs.runCommand "ruby180-i686-rubygems0811-original-sdk"
      { nativeBuildInputs = [ pkgs.makeWrapper ]; }
      ''
        mkdir -p "$out/bin"
        makeWrapper ${ruby}/bin/ruby "$out/bin/ruby" --prefix RUBYLIB : ${gemBase}/lib --prefix RUBYOPT ' ' -rrubygems --suffix GEM_PATH : ${gemBase}/gems --set LC_ALL C
        makeWrapper "$out/bin/ruby" "$out/bin/gem" --add-flags ${gemBase}/bin/gem
        export HOME="$TMPDIR/home" GEM_HOME="$TMPDIR/gems" GEM_PATH="$TMPDIR/gems"
        mkdir -p "$HOME" "$GEM_HOME"
        "$out/bin/gem" --version
        "$out/bin/ruby" -e 'require_gem "sources", "= 0.0.1";require "sources";raise unless RUBY_VERSION=="1.8.0" && Gem::RubyGemsVersion=="0.8.11";raise if defined?(RUBY_PATCHLEVEL);raise unless RUBY_PLATFORM=="i686-linux-gnu" && ["pointer"].pack("p").size==4;raise if Kernel.instance_methods.map{|m|m.to_s}.include?("gem");raise if Gem.respond_to?(:loaded_specs);puts "NATIVE-0811|#{RUBY_VERSION}|#{RUBY_PLATFORM}|#{["pointer"].pack("p").size}|#{Gem::RubyGemsVersion}|require_gem|NO-gem|NO-loaded_specs"'
      '';
in
{
  inherit
    sdk
    ruby
    gemBase
    archive
    ;
}
