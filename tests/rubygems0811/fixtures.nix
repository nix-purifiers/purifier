# SPDX-License-Identifier: MIT
{
  pkgs,
  olderRubySource,
  purifier,
  nativeSdkIdentity ? null,
}:
let
  old = import olderRubySource {
    system = "i686-linux";
    config = { };
  };
  parts = import ./sdk.nix { inherit pkgs olderRubySource; };
  sdk = purifier.rubygems0811ConsumerSdk {
    inherit pkgs;
    sdk = parts.sdk;
    runtime = parts.ruby;
    compiler = old.stdenv.gcc;
    stdenv = old.stdenv;
    sdkBuild = parts.gemBase;
    components = [
      {
        name = "ruby";
        version = "1.8.0";
        archive = parts.ruby.src;
        library = parts.ruby;
      }
      {
        name = "rubygems";
        version = "0.8.11";
        archive = parts.archive;
        library = parts.gemBase;
      }
    ];
  };
  crc = pkgs.runCommand "ruby180-i686-native20-crc" { } ''
    ${pkgs.python3}/bin/python3 -B ${./crc.py} ${parts.ruby}/bin/ruby ${./crc-cases} ${../../tools/rubygems_0811_sdk.py} "$out"
  '';
  producer = pkgs.runCommand "ruby180-original-pure-producer" { } ''
        test -e ${crc}/receipt.json
        mkdir -p "$out"
        ${pkgs.python3}/bin/python3 -B - ${./input} "$out" <<'PYINPUT'
    from pathlib import Path
    import gzip,hashlib,io,json,shutil,sys,tarfile
    source,output=map(Path,sys.argv[1:]);p=json.loads((source/'provenance.json').read_text());archive=source/p['archive']
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==p['archiveSha256']
    assert hashlib.sha256((source/'generation.aterm').read_bytes()).hexdigest()==p['generationATermSha256']
    with tarfile.open(archive) as outer:
     metadata=gzip.decompress(outer.extractfile('metadata.gz').read())
     assert hashlib.sha256(metadata).hexdigest()==p['metadataSha256']
     with tarfile.open(fileobj=io.BytesIO(gzip.decompress(outer.extractfile('data.tar.gz').read())))as payload:
      data=payload.extractfile(p['payloadMember']).read()
      assert data==(source/'ancient_leaf.rb').read_bytes()
      assert hashlib.sha256(data).hexdigest()==p['payloadSha256']
    shutil.copyfile(archive,output/p['archive'])
    PYINPUT
  '';
  projectionArgs = {
    archives = [ "${producer}/ancient_leaf-1.0.0.gem" ];
    inherit producer nativeSdkIdentity;
    roots = [ "ancient_leaf" ];
    ruby = pkgs.ruby;
    indexRuby = pkgs.ruby;
    runCommand = pkgs.runCommand;
    versionScheme = "legacy-numeric-v1";
    legacyIndexRuby = sdk;
    legacyIndexProfile = "ruby180-rubygems0811-i686-v1";
    legacyIndexAttestation = sdk.consumerAttestation;
  };
  projection = purifier.rubygemsProjections projectionArgs;
  reused = purifier.rubygemsProjections (
    projectionArgs
    // {
      archives = [ ];
      producer = pkgs.writeText "ruby180-provided-reuse" "provided native archive byte identity";
      dependencies = [ (producer // { projections = projection; }) ];
    }
  );
  nativeProof =
    fallback:
    pkgs.runCommand
      (if fallback then "ruby180-i686-original-yaml-fallback" else "ruby180-i686-original-native-http")
      { }
      ''
        cmp ${projection.rubygems.catalog} ${reused.rubygems.catalog}
        for archive in ${projection.rubygems}/gems/*.gem; do
          cmp "$archive" "${reused.rubygems}/gems/''${archive##*/}"
        done
        cmp ${projection.rubygems}/yaml ${reused.rubygems}/yaml
        cmp ${projection.rubygems}/yaml.Z ${reused.rubygems}/yaml.Z
        ${pkgs.python3}/bin/python3 -B ${./native.py} ${sdk} ${projection.rubygems} ${producer} ${crc} "$out" ${../../tools/rubygems_0811_sdk.py} ${pkgs.lib.optionalString fallback "--yaml-fallback"}
      '';

in
{
  inherit sdk crc;
  attestation = sdk.consumerAttestationPackage;
  repository = projection.rubygems;
  reusedRepository = reused.rubygems;
  native =
    assert pkgs.lib.assertMsg (
      nativeSdkIdentity != null
    ) "CI requires the actual freshly built attestation identity";
    nativeProof false;
  nativeFallback =
    assert pkgs.lib.assertMsg (
      nativeSdkIdentity != null
    ) "CI requires the actual freshly built attestation identity";
    nativeProof true;
}
