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
    builtins.elem legacyIndexProfile [
      "ruby182-rubygems094-v1"
      "ruby180-rubygems0811-i686-v1"
    ]
    && versionScheme == "legacy-numeric-v1"
    && legacyIndexAttestation != null
) "native consumer requires its explicit index profile and separate consumer attestation";
let
  sdk094 = legacyIndexProfile == "ruby182-rubygems094-v1";
  sdk0811 = legacyIndexProfile == "ruby180-rubygems0811-i686-v1";
  explicitConsumer = sdk094 || sdk0811;
  consumerProbe =
    if sdk0811 then ../../tools/rubygems_0811_probe.rb else ../../tools/rubygems_consumer_sdk_probe.rb;
  consumerContract =
    if sdk0811 then
      ../../tools/rubygems_0811_contract.rb
    else
      ../../tools/rubygems_consumer_sdk_contract.rb;
  legacyIndexer =
    if sdk0811 then
      ../../tools/rubygems_0811_index.rb
    else if sdk094 then
      ../../tools/rubygems_094_index.rb
    else
      ../../tools/rubygems_legacy_index.rb;
  sdk094Encoder = runCommand "rubygems094-index-encoder-identity" {
    writer = ../../tools/rubygems_094_index.rb;
    probe = ../../tools/rubygems_consumer_sdk_probe.rb;
    contract = ../../tools/rubygems_consumer_sdk_contract.rb;
  } "touch $out";
  sdk0811Encoder = runCommand "rubygems0811-index-encoder-identity" {
    writer = ../../tools/rubygems_0811_index.rb;
    probe = consumerProbe;
    contract = consumerContract;
    verifier = ../../tools/rubygems_0811_sdk.py;
    sourcesHelper = ../../tools/rubygems_0811_sources_spec.rb;
  } "touch $out";
  selectedEncoder = if sdk0811 then sdk0811Encoder else sdk094Encoder;
  # Nix itself exports the actual executed SDK's references. Do not trust a
  # caller-provided list or the SDK's consumerClosure passthru for this join.
  sdk094Closure =
    runCommand
      (
        if sdk0811 then
          "rubygems0811-authoritative-sdk-closure"
        else
          "rubygems094-authoritative-sdk-closure"
      )
      {
        __structuredAttrs = true;
        exportReferencesGraph.consumerSdk = [ legacyIndexRuby ];
      }
      ''
        out=''${outputs[out]}
        ${ruby}/bin/ruby -r json -e 'document=JSON.parse(File.read(ENV.fetch("NIX_ATTRS_JSON_FILE"))); puts document.fetch("consumerSdk").map { |entry| entry.fetch("path") }.sort' > "$out"
      '';
  indexProfileFields = lib.optionalAttrs explicitConsumer {
    nativeIndexProfile = legacyIndexProfile;
    nativeIndexEncoderIdentity = (inputIdentity selectedEncoder).hash;
    nativeConsumerAttestationIdentity = (inputIdentity legacyIndexAttestation).hash;
    nativeIndexClosureIdentity = (inputIdentity sdk094Closure).hash;
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
    // lib.optionalAttrs explicitConsumer {
      consumerAttestation = legacyIndexAttestation;
      consumerSdkContract = consumerContract;
      consumerClosure = sdk094Closure;
      indexProfile = legacyIndexProfile;
    }
  ) "touch $out";
  # Generated archives identify their immutable producer and selection without
  # inspecting an output during evaluation. Plain archive inputs keep their
  # existing content identity and API.
  safeMember =
    value:
    builtins.isString value
    && value != ""
    && builtins.match ".*[[:cntrl:]].*" value == null
    && !(lib.hasInfix "\\" value)
    && lib.all (part: part != "" && part != "." && part != "..") (lib.splitString "/" value);
  archiveInputs = map (
    archive:
    if builtins.isAttrs archive && !(lib.isDerivation archive) then
      assert lib.assertMsg
        (
          builtins.attrNames archive == [
            "path"
            "producer"
            "type"
          ]
          && archive.type == "generated-gem"
          && (archive.path == null || safeMember archive.path)
        )
        "generated RubyGems archive needs type, immutable producer and a safe relative path (or null for a file output)";
      let
        root = toString archive.producer;
        producerIdentity = inputIdentity archive.producer;
        selection = {
          type = archive.type;
          producer = root;
          path = archive.path;
        };
      in
      builtins.deepSeq producerIdentity {
        archive = root + lib.optionalString (archive.path != null) ("/" + archive.path);
        generated = selection;
        identity = builtins.hashString "sha256" (
          builtins.toJSON {
            format = "purifier-generated-gem-v1";
            inherit selection;
            producer = producerIdentity.hash;
          }
        );
      }
    else
      {
        inherit archive;
        generated = null;
        identity =
          (inputIdentity (
            builtins.path {
              path = archive;
              name = "gem";
            }
          )).hash;
      }
  ) archives;
  selectedArchives = map (input: input.archive) archiveInputs;
  generatedArchives = map (input: input.generated) (
    builtins.filter (input: input.generated != null) archiveInputs
  );
  archiveIdentities = builtins.listToAttrs (
    map (input: {
      name = builtins.unsafeDiscardStringContext (toString input.archive);
      value = input.identity;
    }) archiveInputs
  );
  identity = runCommand "${name}-identity" {
    producerIdentity = (inputIdentity producer).hash;
    projector = ../../tools/rubygems_repository.rb;
    codec = ../../tools/rubygems_codec.rb;
    versionSchemes = ../../tools/rubygems_version_scheme.rb;
    indexer = ../../tools/rubygems_index.rb;
    indexRuntime = indexRuby;
    nativeBuildInputs = [ ruby ];
    archives = builtins.toJSON selectedArchives;
    generatedArchives = builtins.toJSON generatedArchives;
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
            archives = selectedArchives;
            inherit
              generatedArchives
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
        ${lib.optionalString explicitConsumer ''
          ${legacyIndexRuby}/bin/purifier-verify-consumer-sdk ${lib.escapeShellArg (toString legacyIndexAttestation)} ${legacyIndexRuby}/bin/ruby ${sdk094Closure}
        ''}
        PURIFIER_RUBYGEMS_CODEC_PRELOADED=1 PURIFIER_RUBYGEMS_VERSION_SCHEME_PRELOADED=1 PURIFIER_RUBYGEMS_SEPARATE_INDEX=1 \
          ${ruby}/bin/ruby -r ${../../tools/rubygems_codec.rb} -r ${../../tools/rubygems_version_scheme.rb} ${lib.optionalString explicitConsumer "-r ${consumerContract}"} ${../../tools/rubygems_repository.rb} "$specPath" \
          "$out" "$metadata/catalog.json"
        ${lib.optionalString (!explicitConsumer) ''
          ${indexRuby}/bin/ruby ${../../tools/rubygems_index.rb} "$out" "$metadata/catalog.json"
        ''}
        ${lib.optionalString (legacyIndexRuby != null) ''
          ${lib.optionalString explicitConsumer ''
            unset RUBYOPT RUBYLIB RUBYGEMS_GEMDEPS
            export HOME="$TMPDIR/ordinary-consumer-home" GEM_HOME="$TMPDIR/ordinary-consumer-gems" GEM_PATH="$TMPDIR/ordinary-consumer-gems"
            mkdir -p "$HOME" "$GEM_HOME"
            export PURIFIER_CONSUMER_PROBE=${consumerProbe}
            export PURIFIER_CONSUMER_CONTRACT=${consumerContract}
          ''}
          ${lib.optionalString sdk0811 ''
            ${ruby}/bin/ruby -r ${consumerContract} -e 'value=PurifierRubyGems0811Contract.read!(ARGV.fetch(0),ARGV.fetch(1)); puts PurifierRubyGems0811Contract.canonical(value.fetch("observation"))' ${lib.escapeShellArg (toString legacyIndexAttestation)} ${lib.escapeShellArg nativeSdkIdentity} > "$TMPDIR/verified0811-observation.json"
          ''}
          ${legacyIndexRuby}/bin/ruby ${legacyIndexer} "$out" ${
            if sdk0811 then
              ''"$TMPDIR/verified0811-observation.json"''
            else
              lib.optionalString sdk094 (lib.escapeShellArg (toString legacyIndexAttestation))
          }
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
