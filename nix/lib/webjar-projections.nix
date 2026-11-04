# SPDX-License-Identifier: MIT
# Package a built browser asset directory as a WebJar, then use the shared
# publisher for immutable Maven/Ivy identities and catalogs.
{ lib }:
{
  producer,
  assets,
  artifactId,
  version,
  groupId ? "org.webjars.npm",
  runCommand,
  python3,
  name ? "webjar-projection",
}:
let
  inputIdentity = import ./input-identity.nix { inherit lib; };
  repository =
    runCommand "${name}-repository"
      {
        nativeBuildInputs = [ python3 ];
        spec = builtins.toJSON {
          inherit artifactId version groupId;
          assets = toString assets;
          producer = (inputIdentity producer).hash;
        };
        passAsFile = [ "spec" ];
      }
      ''
        python ${../../tools/cross_type.py} webjar "$specPath" "$out"
        mkdir -p "$out/nix-support"
        printf '%s\n' ${lib.escapeShellArg (toString producer)} > "$out/nix-support/inputs"
      '';
in
import ./jvm-projections.nix { inherit lib; } {
  inherit
    repository
    producer
    runCommand
    python3
    name
    ;
  formats = [
    "maven"
    "ivy"
  ];
}
