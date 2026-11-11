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
  # Retain actual derivation bytes without realizing unrelated bootstrap
  # outputs. Index SDK/encoder/attestation inputIdentity contexts stay intact.
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
  wrapper =
    pkgs.runCommand name
      {
        passthru = {
          consumerAttestation = "${attestation}/consumer-sdk.json";
          consumerAttestationPackage = attestation;
          consumerClosure = "${closure}/store-paths";
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
        export PURIFIER_CONSUMER_PROBE=${../../tools/rubygems_consumer_sdk_probe.rb}
        exec ${pkgs.python3}/bin/python3 ${../../tools/rubygems_consumer_sdk.py} --verify \\
          ${descriptor} "\$3" ${pkgs.nix}/bin/nix "\$1" "\$2"
        EOF
        chmod +x "$out/bin/purifier-verify-consumer-sdk"
      '';
  # The wrapper contains no attestation or closure-file reference. Measuring
  # its complete runtime closure therefore creates no hash self-reference.
  closure = pkgs.closureInfo { rootPaths = [ wrapper ]; };
  attestation = pkgs.runCommand "${name}-attestation" { } ''
    mkdir -p "$out"
    PURIFIER_CONSUMER_PROBE=${../../tools/rubygems_consumer_sdk_probe.rb} \
      ${pkgs.python3}/bin/python3 ${../../tools/rubygems_consumer_sdk.py} ${descriptor} \
      ${closure}/store-paths ${pkgs.nix}/bin/nix \
      "$out/consumer-sdk.json" ${wrapper}/bin/ruby
    ${pkgs.ruby}/bin/ruby -r ${../../tools/rubygems_consumer_sdk_contract.rb} \
      -e 'PurifierRubyGemsConsumerSDKContract.read!(ARGV.fetch(0))' \
      "$out/consumer-sdk.json"
  '';
in
wrapper
