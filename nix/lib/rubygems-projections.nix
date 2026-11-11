# SPDX-License-Identifier: MIT
{ lib }:
let
  inputIdentity = import ./input-identity.nix { inherit lib; };
  projectInputs = import ./project-inputs.nix { inherit lib; };
in
{
  archives,
  producer,
  roots ? null,
  intrinsics ? [ ],
  dependencies ? [ ],
  ruby,
  indexRuby ? ruby,
  runCommand,
  name ? "rubygems-projection",
  versionScheme ? "nix-prerelease-v1",
  nativeSdkIdentity ? null,
  legacyIndexRuby ? null,
  legacyIndexProfile ? null,
  legacyIndexAttestation ? null,
}:
assert lib.assertMsg (builtins.elem versionScheme [
  "nix-prerelease-v1"
  "legacy-numeric-v1"
]) "unsupported RubyGems version scheme";
assert lib.assertMsg (
  if versionScheme == "legacy-numeric-v1" then
    builtins.isString nativeSdkIdentity
    && builtins.match "sha256-[A-Za-z0-9+/]{43}=" nativeSdkIdentity != null
  else
    nativeSdkIdentity == null
) "numeric RubyGems projection requires an exact SDK identity";
assert lib.assertMsg (
  (versionScheme == "legacy-numeric-v1") == (legacyIndexRuby != null)
) "numeric RubyGems projection requires its explicit native index SDK";
assert lib.assertMsg (
  if legacyIndexProfile == null then
    legacyIndexAttestation == null
  else
    legacyIndexProfile == "ruby182-rubygems094-v1"
    && versionScheme == "legacy-numeric-v1"
    && legacyIndexAttestation != null
) "SDK094 requires its explicit index profile and separate consumer attestation";
let
  sdk094 = legacyIndexProfile == "ruby182-rubygems094-v1";
  legacyIndexer =
    if sdk094 then ../../tools/rubygems_094_index.rb else ../../tools/rubygems_legacy_index.rb;
  sdk094Encoder = runCommand "rubygems094-index-encoder-identity" {
    writer = ../../tools/rubygems_094_index.rb;
    probe = ../../tools/rubygems_consumer_sdk_probe.rb;
    contract = ../../tools/rubygems_consumer_sdk_contract.rb;
  } "touch $out";
  indexProfileFields = lib.optionalAttrs sdk094 {
    nativeIndexProfile = legacyIndexProfile;
    nativeIndexEncoderIdentity = (inputIdentity sdk094Encoder).hash;
    nativeConsumerAttestationIdentity = (inputIdentity legacyIndexAttestation).hash;
    nativeConsumerAttestation = toString legacyIndexAttestation;
  };
  selected = projectInputs {
    inherit dependencies;
    formats = [ "rubygems" ];
  };
  repositories = map (input: {
    repository = toString input.repository;
    catalog = input.repository.catalog;
  }) selected;
  toolchain = runCommand "rubygems-projector-toolchain" (
    {
      projector = ../../tools/rubygems_repository.rb;
      codec = ../../tools/rubygems_codec.rb;
      versionSchemes = ../../tools/rubygems_version_scheme.rb;
      indexer = ../../tools/rubygems_index.rb;
      indexRuntime = indexRuby;
      nativeBuildInputs = [ ruby ];
    }
    // lib.optionalAttrs (legacyIndexRuby != null) {
      inherit legacyIndexer;
      legacyIndexRuntime = legacyIndexRuby;
    }
    // lib.optionalAttrs sdk094 {
      consumerAttestation = legacyIndexAttestation;
      consumerSdkContract = ../../tools/rubygems_consumer_sdk_contract.rb;
      indexProfile = legacyIndexProfile;
    }
  ) "touch $out";
  archiveIdentities = builtins.listToAttrs (
    map (archive: {
      name = builtins.unsafeDiscardStringContext (toString archive);
      value =
        (inputIdentity (
          builtins.path {
            path = archive;
            name = "gem";
          }
        )).hash;
    }) archives
  );
  identity = runCommand "${name}-identity" {
    producerIdentity = (inputIdentity producer).hash;
    projector = ../../tools/rubygems_repository.rb;
    codec = ../../tools/rubygems_codec.rb;
    versionSchemes = ../../tools/rubygems_version_scheme.rb;
    indexer = ../../tools/rubygems_index.rb;
    indexRuntime = indexRuby;
    nativeBuildInputs = [ ruby ];
    archives = builtins.toJSON archives;
    dependencies = builtins.toJSON repositories;
  } "touch $out";
  projection =
    runCommand name
      {
        outputs = [
          "out"
          "metadata"
        ];
        nativeBuildInputs = [ ruby ];
        spec = builtins.toJSON (
          {
            identity = (inputIdentity identity).hash;
            inherit
              archives
              archiveIdentities
              roots
              intrinsics
              ;
            projectorIdentity = (inputIdentity toolchain).hash;
            dependencies = repositories;
          }
          // lib.optionalAttrs (versionScheme != "nix-prerelease-v1" || nativeSdkIdentity != null) {
            inherit versionScheme nativeSdkIdentity;
            nativeIndexIdentity =
              if legacyIndexRuby == null then null else (inputIdentity legacyIndexRuby).hash;
          }
          // indexProfileFields
        );
        passAsFile = [ "spec" ];
        passthru.catalog = "${projection.metadata}/catalog.json";
      }
      ''
        ${lib.optionalString sdk094 ''
          ${legacyIndexRuby}/bin/purifier-verify-consumer-sdk ${lib.escapeShellArg (toString legacyIndexAttestation)} ${legacyIndexRuby}/bin/ruby
        ''}
        PURIFIER_RUBYGEMS_CODEC_PRELOADED=1 PURIFIER_RUBYGEMS_VERSION_SCHEME_PRELOADED=1 PURIFIER_RUBYGEMS_SEPARATE_INDEX=1 \
          ${ruby}/bin/ruby -r ${../../tools/rubygems_codec.rb} -r ${../../tools/rubygems_version_scheme.rb} ${lib.optionalString sdk094 "-r ${../../tools/rubygems_consumer_sdk_contract.rb}"} ${../../tools/rubygems_repository.rb} "$specPath" \
          "$out" "$metadata/catalog.json"
        ${lib.optionalString (!sdk094) ''
          ${indexRuby}/bin/ruby ${../../tools/rubygems_index.rb} "$out" "$metadata/catalog.json"
        ''}
        ${lib.optionalString (legacyIndexRuby != null) ''
          ${lib.optionalString sdk094 ''
            unset RUBYOPT RUBYLIB RUBYGEMS_GEMDEPS
            export HOME="$TMPDIR/ordinary-consumer-home" GEM_HOME="$TMPDIR/ordinary-consumer-gems" GEM_PATH="$TMPDIR/ordinary-consumer-gems"
            mkdir -p "$HOME" "$GEM_HOME"
            export PURIFIER_CONSUMER_PROBE=${../../tools/rubygems_consumer_sdk_probe.rb}
            export PURIFIER_CONSUMER_CONTRACT=${../../tools/rubygems_consumer_sdk_contract.rb}
          ''}
          ${legacyIndexRuby}/bin/ruby ${legacyIndexer} "$out" ${lib.optionalString sdk094 (lib.escapeShellArg (toString legacyIndexAttestation))}
        ''}
        mkdir -p "$out/nix-support"
        printf '%s\n' ${
          lib.escapeShellArgs (
            [ (toString producer) ]
            ++ lib.concatMap (input: [
              (toString input.repository)
              (toString input.producer)
            ]) selected
          )
        } \
          > "$out/nix-support/inputs"
      '';
in
{
  rubygems = projection.out;
}
