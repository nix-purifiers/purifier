# SPDX-License-Identifier: MIT
{ lib }:
{
  producer,
  roots,
  dependencies ? [ ],
  schema ? null,
  runCommand,
  python3,
  name ? "resource-projection",
}:
let
  inputIdentity = import ./input-identity.nix { inherit lib; };
  projection =
    runCommand name
      {
        nativeBuildInputs = [ python3 ];
        spec = builtins.toJSON {
          producer = toString producer;
          producerIdentity = (inputIdentity producer).hash;
          inherit roots schema;
          dependencies = map (dependency: {
            path = toString dependency;
            identity = (inputIdentity dependency).hash;
          }) dependencies;
        };
        passAsFile = [ "spec" ];
        passthru = {
          directory = "${projection}/files";
          documentRoot = "${projection}/files";
          classPath = "${projection}/resources.jar";
          catalog = "${projection}/catalog.json";
        };
      }
      ''
        python ${../../tools/resource_projection.py} "$specPath" "$out"
      '';
in
assert
  roots != { } || throw "purifier: resourceProjections requires explicitly selected output roots";
{
  resources = projection;
  web = projection;
  java-resources = projection;
}
