# SPDX-License-Identifier: MIT
{ pkgs, purifier }:
let
  inherit (pkgs) lib runCommand;
  native = runCommand "generated-gem-descriptor-fixture" { nativeBuildInputs = [ pkgs.ruby ]; } ''
    mkdir -p lib "$out/gems"
    echo 'GeneratedDependency = 41' > lib/generated_dependency.rb
    echo "require 'generated_dependency'; GeneratedConsumer = GeneratedDependency + 1" > lib/generated_consumer.rb
    ruby -e '
      require "rubygems/package"
      %w[dependency consumer].each do |part|
        spec = Gem::Specification.new do |s|
          s.name = "generated-#{part}"; s.version = "1.2.3"
          s.authors = ["fixture"]; s.summary = "Generated descriptor fixture"
          s.files = ["lib/generated_#{part}.rb"]
          s.add_runtime_dependency("generated-dependency", "= 1.2.3") if part == "consumer"
        end
        Gem::Package.build(spec)
      end
    '
    cp *.gem "$out/gems/"
    cp generated-dependency-1.2.3.gem "$out/gems/alias.gem"
    ln -s ${pkgs.writeText "not-a-gem" "outside"} "$out/escape.gem"
    echo 'not a gem' > "$out/invalid.gem"
  '';
  descriptor = path: {
    type = "generated-gem";
    producer = native;
    inherit path;
  };
  project =
    archives:
    purifier.rubygemsProjections {
      inherit archives;
      producer = native;
      inherit (pkgs) ruby runCommand;
    };
  directory = project [
    (descriptor "gems/generated-dependency-1.2.3.gem")
    (descriptor "gems/generated-consumer-1.2.3.gem")
  ];
  file = runCommand "generated-gem-descriptor-file" { } ''
    cp ${native}/gems/generated-dependency-1.2.3.gem "$out"
  '';
  single = project [
    {
      type = "generated-gem";
      producer = file;
      path = null;
    }
  ];
  alias = project [ (descriptor "gems/alias.gem") ];
  original = project [ (descriptor "gems/generated-dependency-1.2.3.gem") ];
  other = runCommand "independent-generated-gem-root" { } ''cp -r ${native} "$out"'';
  independent = project [
    {
      type = "generated-gem";
      producer = other;
      path = "gems/alias.gem";
    }
  ];
  identities =
    view:
    builtins.attrValues (builtins.fromJSON (builtins.unsafeDiscardStringContext view.rubygems.spec))
      .archiveIdentities;
  rejects =
    value: !(builtins.tryEval (builtins.deepSeq (project [ value ]).rubygems.drvPath true)).success;
  unsafe = [
    ""
    "/absolute.gem"
    "../escape.gem"
    "a/../escape.gem"
    "a//b.gem"
    "./a.gem"
    "a\\b.gem"
    "a\nb.gem"
  ];
in
{
  rubygems-generated-evaluation =
    assert identities alias != identities independent;
    assert identities alias != identities original;
    assert builtins.hasAttr (builtins.unsafeDiscardStringContext native.drvPath) (
      builtins.getContext directory.rubygems.spec
    );
    assert lib.all (path: rejects (descriptor path)) unsafe;
    assert rejects {
      type = "unknown";
      producer = native;
      path = null;
    };
    assert rejects {
      type = "generated-gem";
      producer = "/tmp/ambient";
      path = null;
    };
    assert rejects ((descriptor "x.gem") // { version = "guessed"; });
    runCommand "generated-gem-descriptor-evaluation" {
      directoryDrv = directory.rubygems.drvPath;
      singleDrv = single.rubygems.drvPath;
    } ''touch "$out"'';

  rubygems-generated-native =
    runCommand "generated-gem-descriptor-native" { nativeBuildInputs = [ pkgs.ruby ]; }
      ''
        export HOME="$TMPDIR/home" GEM_HOME="$TMPDIR/gems" GEM_PATH="$TMPDIR/gems"
        mkdir -p "$HOME" "$GEM_HOME"
        cd ${directory.rubygems}/gems
        ruby -S gem install --local --prerelease --no-document --install-dir "$GEM_HOME" ./generated-dependency-*.gem
        ruby -S gem install --local --prerelease --no-document --install-dir "$GEM_HOME" ./generated-consumer-*.gem
        ruby -e 'require "generated_consumer"; abort unless GeneratedConsumer == 42'
        ruby -r json -e '
          packages = JSON.parse(File.read(ARGV.fetch(0))).fetch("packages")
          consumer = Gem::Package.new(Dir[ARGV.fetch(1) + "/gems/generated-consumer-*.gem"].fetch(0)).spec
          dependency = packages.find { |p| p.fetch("name") == "generated-dependency" }
          abort unless consumer.runtime_dependencies.fetch(0).requirement.to_s == "= " + dependency.fetch("version")
        ' -r rubygems/package ${directory.rubygems.catalog} ${directory.rubygems}
        test -f ${single.rubygems.catalog}
        touch "$out"
      '';

  rubygems-generated-missing =
    pkgs.testers.testBuildFailure
      (project [ (descriptor "missing.gem") ]).rubygems;
  rubygems-generated-escape =
    pkgs.testers.testBuildFailure
      (project [ (descriptor "escape.gem") ]).rubygems;
  rubygems-generated-invalid =
    pkgs.testers.testBuildFailure
      (project [ (descriptor "invalid.gem") ]).rubygems;
}
