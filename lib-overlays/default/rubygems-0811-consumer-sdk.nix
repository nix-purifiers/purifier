# SPDX-License-Identifier: MIT
# Explicit original0811/i686 profile. Existing094/101 constructors are unchanged.
{ lib }:
{
  pkgs,
  sdk,
  components,
  compiler,
  runtime,
  stdenv,
  sdkBuild,
  name ? "ruby180-rubygems0811-i686-consumer-sdk",
}:
let
  capture = label: value: {
    original = builtins.unsafeDiscardStringContext value.drvPath;
    captured = pkgs.writeText label (
      builtins.unsafeDiscardStringContext (
        builtins.readFile (builtins.unsafeDiscardOutputDependency value.drvPath)
      )
    );
  };
  bootstrapPolicy = {
    format = "original0811-sources-bootstrap";
    schemaVersion = 1;
    date = "1970-01-01";
    timezone = "UTC";
    generatedCache = "absent";
  };
  originalGemArchive =
    (builtins.head (builtins.filter (item: item.name == "rubygems") components)).archive;
  originalSources = pkgs.runCommand "rubygems0811-original-embedded-sources" { } ''
    ${pkgs.python3}/bin/python3 -B ${../../tools/rubygems_0811_sdk.py} extract-original ${originalGemArchive} "$out"
  '';
  descriptor = pkgs.writeText "${name}-components.json" (
    builtins.toJSON {
      schemaVersion = 1;
      profile = "ruby180-rubygems0811-i686-v1";
      inherit bootstrapPolicy originalSources;
      sdk = toString sdk;
      compiler = toString compiler;
      buildEnvironment = toString stdenv;
      runtimeBuild = capture "ruby180-runtime.aterm" runtime;
      stdenvBuild = capture "ruby180-stdenv.aterm" stdenv;
      compilerBuild = capture "ruby180-compiler.aterm" compiler;
      sdkBuild = capture "rubygems0811-bootstrap.aterm" sdkBuild;
      components = map (item: {
        inherit (item) name version;
        archive = toString item.archive;
        library = toString item.library;
      }) components;
    }
  );
  probe = ../../tools/rubygems_0811_probe.rb;
  verifier = ../../tools/rubygems_0811_sdk.py;
  sourcesHelper = ../../tools/rubygems_0811_sources_spec.rb;
  wrapper =
    pkgs.runCommand name
      {
        passthru = {
          consumerAttestation = "${attestation}/consumer-sdk.json";
          consumerAttestationPackage = attestation;
          consumerClosure = "${closure}/store-paths";
          consumerProfile = "ruby180-rubygems0811-i686-v1";
        };
      }
      ''
        mkdir -p "$out/bin" "$out/share/purifier"
        ln -s ${sdk}/bin/ruby "$out/bin/ruby"
        ln -s ${sdk}/bin/gem "$out/bin/gem"
        cp ${descriptor} "$out/share/purifier/consumer-components.json"
        cat > "$out/bin/purifier-verify-consumer-sdk" <<EOF
        #!${pkgs.runtimeShell}
        set -eu
        exec ${pkgs.python3}/bin/python3 -B ${verifier} verify \\
          ${descriptor} "\$3" ${pkgs.nix}/bin/nix "\$1" "\$2" ${probe} ${sourcesHelper}
        EOF
        chmod +x "$out/bin/purifier-verify-consumer-sdk"
      '';
  closure = pkgs.closureInfo { rootPaths = [ wrapper ]; };
  attestation = pkgs.runCommand "${name}-attestation" { } ''
    mkdir -p "$out"
    ${pkgs.python3}/bin/python3 -B ${verifier} create ${descriptor} \
      ${closure}/store-paths ${pkgs.nix}/bin/nix "$out/consumer-sdk.json" \
      ${wrapper}/bin/ruby ${probe} ${sourcesHelper}
    ${pkgs.ruby}/bin/ruby -r ${../../tools/rubygems_0811_contract.rb} \
      -e 'PurifierRubyGems0811Contract.read!(ARGV.fetch(0))' "$out/consumer-sdk.json"
  '';
in
wrapper
