# SPDX-License-Identifier: MIT
{ lib }:
{
  producer,
  modules,
  runCommand,
  python3,
  nodejs,
  name ? "wasm-projection",
}:
let
  resources = (import ./resource-projections.nix { inherit lib; }) {
    inherit producer runCommand python3;
    roots = lib.mapAttrs' (logical: module: {
      name = "${logical}.wasm";
      value = module.path;
    }) modules;
  };
  projection =
    runCommand name
      {
        nativeBuildInputs = [ nodejs ];
        spec = builtins.toJSON modules;
        passAsFile = [ "spec" ];
        passthru = {
          directory = "${projection}/files";
          documentRoot = "${projection}/files";
          classPath = "${projection}/resources.jar";
          catalog = "${projection}/catalog.json";
        };
      }
      ''
        cp -r ${resources.resources} "$out"
        chmod -R u+w "$out"
        node ${../../tools/wasm_projection.cjs} "$specPath" "$out"
      '';
in
assert modules != { } || throw "purifier: wasmProjections needs explicitly selected core modules";
assert
  builtins.all (
    logical: builtins.match "[A-Za-z0-9_][A-Za-z0-9_.-]*" logical != null && !lib.hasInfix ".." logical
  ) (builtins.attrNames modules)
  || throw "purifier: invalid logical WebAssembly module name";
{
  wasm = projection // {
    catalog = "${projection}/wasm.json";
    modules = lib.mapAttrs (logical: _: "${projection}/files/${logical}.wasm") modules;
  };
  resources = projection;
  web = projection;
  java-resources = projection;
}
