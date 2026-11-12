# SPDX-License-Identifier: MIT
# Publish evaluated JSON documents, not the producer's source/environment.
{ lib }:
{
  producer,
  files,
  runCommand,
  python3,
  name ? "json-data-projection",
}:
let
  inputIdentity = import ./input-identity.nix { inherit lib; };
  projection =
    runCommand name
      {
        outputs = [
          "out"
          "metadata"
        ];
        nativeBuildInputs = [ python3 ];
        spec = builtins.toJSON {
          producer = toString producer;
          producerIdentity = (inputIdentity producer).hash;
          inherit files;
        };
        passAsFile = [ "spec" ];
        passthru = {
          catalog = "${projection.metadata}/catalog.json";
          files = lib.mapAttrs (_: file: "${projection}/${file}") files;
        };
      }
      ''
        python ${../../tools/cross_type.py} json "$specPath" "$out" "$metadata"
      '';
in
assert files != { } || throw "purifier: dataProjections needs at least one evaluated JSON document";
{
  json = projection.out;
}
