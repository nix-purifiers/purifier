# SPDX-License-Identifier: MIT
{
  pkgs,
  olderRubySource,
  purifier,
}:
let
  old = import olderRubySource {
    system = "i686-linux";
    config = { };
  };
  recipes = import ./recipes-v1.nix { inherit pkgs olderRubySource; };
  inherit (recipes) runtime generator;
  archive = pkgs.fetchurl {
    url = "https://i.loveruby.net/archive/racc/racc-1.4.4-all.tar.gz";
    sha256 = "4532f638fe2868c7e1ecbd52a7345ceca9a841038fceb12be1e153ee4f082660";
  };
  producer =
    pkgs.runCommand "racc-1.4.4-original-resource-producer"
      {
        passthru.projections = purifier.resourceProjections {
          inherit producer;
          roots = {
            generator = "packages/racc";
            runtime = "packages/raccrt/lib";
            sample = "generated";
          };
          inherit (pkgs) runCommand python3;
        };
      }
      ''
        mkdir "$out"
        tar -xzf ${archive} -C "$out" --strip-components=1
        mkdir "$out/generated"
        export RUBYLIB="$out/packages/racc/lib:$out/packages/raccrt/lib"
        unset RUBYOPT GEM_HOME GEM_PATH
        ${generator}/bin/ruby -e 'raise unless RUBY_VERSION=="1.8.0";raise if defined?(Gem);puts [RUBY_VERSION,RUBY_RELEASE_DATE,RUBY_PLATFORM].join("|")' > "$out/generated/generator-runtime.txt"
        # Original documented option avoids random line-conversion eval labels.
        ${generator}/bin/ruby "$out/packages/racc/bin/racc" --no-line-convert -o "$out/generated/calc.rb" "$out/packages/racc/sample/calc.y" > "$out/generated/generator.stdout" 2> "$out/generated/generator.stderr"
      '';
  selected = builtins.head (
    purifier.projectInputs {
      dependencies = [ producer ];
      formats = [ "resources" ];
    }
  );
  projection = selected.repository;
  closure = pkgs.closureInfo {
    rootPaths = [
      runtime
      generator
      producer
      projection
      old.stdenv
      old.stdenv.gcc
      runtime.src
      generator.src
      archive
    ];
  };
  descriptor = pkgs.writeText "ruby160-resource-inputs.json" (
    builtins.toJSON {
      runtime = toString runtime;
      generator = toString generator;
      producer = toString producer;
      projection = toString projection;
      compiler = toString old.stdenv.gcc;
      stdenv = toString old.stdenv;
      runtimeArchive = toString runtime.src;
      generatorArchive = toString generator.src;
      raccArchive = toString archive;
      selectedFormat = selected.format;
      producerIdentity = selected.identity.hash;
      projectionIdentity = selected.repositoryIdentity.hash;
    }
  );
  native = pkgs.runCommand "ruby160-original-resource-consumption" { } ''
    ${pkgs.python3}/bin/python3 -B ${./native.py} ${descriptor} ${closure}/store-paths ${../../tools/rubygems_0811_sdk.py} ${pkgs.nix}/bin/nix "$out"
  '';
in
{
  inherit
    runtime
    generator
    archive
    producer
    projection
    native
    ;
}
