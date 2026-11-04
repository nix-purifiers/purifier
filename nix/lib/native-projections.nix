# SPDX-License-Identifier: MIT
# Explicit shared-library paths from a built producer. No ABI or binding
# generation is implied: callers supply compatible C/JNI/FFM signatures.
{ lib }:
{
  producer,
  libraries,
  system,
  runCommand,
  python3,
  name ? "native-projection",
}:
let
  inputIdentity = import ./input-identity.nix { inherit lib; };
  projection =
    runCommand name
      {
        nativeBuildInputs = [ python3 ];
        spec = builtins.toJSON {
          inherit libraries system;
          producer = toString producer;
          producerIdentity = (inputIdentity producer).hash;
        };
        passAsFile = [ "spec" ];
        passthru = {
          catalog = "${projection}/catalog.json";
          inherit system;
        };
      }
      ''
        python ${../../tools/cross_type.py} native "$specPath" "$out"
      '';
in
assert libraries != { } || throw "purifier: nativeProjections needs at least one shared library";
{
  native = projection;
  python-ffi = projection;
  java-ffi = projection;
}
