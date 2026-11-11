# SPDX-License-Identifier: MIT
# A separate ordinary-consumer SDK; incidental Bundler is never activated.
{ lib }:
{
  pkgs,
  sdk,
  components,
  compiler,
  nativeGems,
  name ? "ruby182-rubygems094-consumer-sdk",
}:
let
  # Read the actual derivation files without realizing every historical
  # compiler bootstrap output. This does not change index inputIdentity.
  captureDerivation =
    label: path:
    pkgs.writeText label (
      builtins.unsafeDiscardStringContext (
        builtins.readFile (builtins.unsafeDiscardOutputDependency path)
      )
    );
  nativeBuildDerivation = captureDerivation "native-gems.aterm" nativeGems.drvPath;
  compilerDerivation = captureDerivation "native-compiler.aterm" compiler.drvPath;
  descriptor = pkgs.writeText "${name}-components.json" (
    builtins.toJSON {
      schemaVersion = 1;
      sdk = toString sdk;
      compiler = toString compiler;
      inherit nativeBuildDerivation compilerDerivation;
      originalNativeBuildDerivation = builtins.unsafeDiscardStringContext nativeGems.drvPath;
      originalCompilerDerivation = builtins.unsafeDiscardStringContext compiler.drvPath;
      components = map (item: {
        inherit (item) name version;
        archive = toString item.archive;
        library = toString item.library;
      }) components;
    }
  );
  closure = pkgs.closureInfo {
    rootPaths = [
      sdk
      compiler
      nativeBuildDerivation
      compilerDerivation
    ]
    ++ lib.concatMap (item: [
      item.archive
      item.library
    ]) components;
  };
in
pkgs.runCommand name
  {
    nativeBuildInputs = [
      pkgs.python3
      pkgs.nix
    ];
    passthru.consumerAttestation = "share/purifier/consumer-sdk.json";
  }
  ''
    mkdir -p "$out/bin" "$out/share/purifier"
    ln -s ${sdk}/bin/ruby "$out/bin/ruby"
    ln -s ${sdk}/bin/gem "$out/bin/gem"
    cp ${descriptor} "$out/share/purifier/consumer-components.json"
    cat > "$out/bin/purifier-verify-consumer-sdk" <<EOF
    #!${pkgs.runtimeShell}
    set -eu
    export PURIFIER_CONSUMER_PROBE=${../../tools/rubygems_consumer_sdk_probe.rb}
    exec ${pkgs.python3}/bin/python3 ${../../tools/rubygems_consumer_sdk.py} --verify \\
      ${descriptor} ${closure}/store-paths ${pkgs.nix}/bin/nix "\$1" "\$2"
    EOF
    chmod +x "$out/bin/purifier-verify-consumer-sdk"
    PURIFIER_CONSUMER_PROBE=${../../tools/rubygems_consumer_sdk_probe.rb} \
      python3 ${../../tools/rubygems_consumer_sdk.py} ${descriptor} \
      ${closure}/store-paths ${pkgs.nix}/bin/nix \
      "$out/share/purifier/consumer-sdk.json"
    ${pkgs.ruby}/bin/ruby -r ${../../tools/rubygems_consumer_sdk_contract.rb} \
      -e 'PurifierRubyGemsConsumerSDKContract.read!(ARGV.fetch(0))' \
      "$out/share/purifier/consumer-sdk.json"
  ''
